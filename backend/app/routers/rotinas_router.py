"""
Diário de Bordo - módulo de rotinas de gestão (18/08/2026).

Não existia nenhum controle estruturado disso antes deste módulo
(confirmado com o usuário) - o "Cumprimento Geral de Rotinas" que
aparecia no MBR até então era apurado manualmente fora do Atlas. Esse
módulo passa a ser a fonte de dados única: cadastro de rotinas
recorrentes (Rotina) + o registro concreto de cada dia (ExecucaoRotina).

Hoje só rotinas de frequência "diaria" geram execução automática (uma
por dia corrido) - "semanal"/"mensal" ainda não têm uma regra de
"quais dias contam" definida, então por enquanto entram só como
cadastro informativo, sem cobrança de execução. Ver Rotina.frequencia.
"""
from datetime import date, datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import requer_papel, obter_usuario_atual
from ..audit import registrar_log

router = APIRouter(prefix="/rotinas", tags=["rotinas"])


@router.get("", response_model=list[schemas.RotinaOut])
def listar_rotinas(incluir_inativas: bool = False, usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db)):
    q = db.query(models.Rotina)
    if not incluir_inativas:
        q = q.filter(models.Rotina.ativo.is_(True))
    return q.order_by(models.Rotina.setor, models.Rotina.nome).all()


@router.post("", response_model=schemas.RotinaOut)
def criar_rotina(payload: schemas.RotinaCreate, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    if payload.frequencia not in ("diaria", "semanal", "mensal"):
        raise HTTPException(400, "Frequência inválida. Use: diaria, semanal ou mensal.")
    nova = models.Rotina(
        nome=payload.nome, descricao=payload.descricao, setor=payload.setor,
        frequencia=payload.frequencia, responsavel_padrao=payload.responsavel_padrao,
        ativo=True, criado_por=usuario.username,
    )
    db.add(nova)
    registrar_log(db, usuario.username, "criar_rotina", entidade="rotina", detalhes={"nome": payload.nome, "setor": payload.setor})
    db.commit()
    db.refresh(nova)
    return nova


@router.patch("/{rotina_id}", response_model=schemas.RotinaOut)
def atualizar_rotina(rotina_id: int, payload: schemas.RotinaAtualizar, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    rotina = db.query(models.Rotina).get(rotina_id)
    if not rotina:
        raise HTTPException(404, "Rotina não encontrada.")
    if payload.frequencia is not None and payload.frequencia not in ("diaria", "semanal", "mensal"):
        raise HTTPException(400, "Frequência inválida. Use: diaria, semanal ou mensal.")
    for campo in ("nome", "descricao", "setor", "frequencia", "responsavel_padrao", "ativo"):
        valor = getattr(payload, campo)
        if valor is not None:
            setattr(rotina, campo, valor)
    registrar_log(db, usuario.username, "atualizar_rotina", entidade="rotina", entidade_id=rotina_id)
    db.commit()
    db.refresh(rotina)
    return rotina


@router.delete("/{rotina_id}")
def excluir_rotina(rotina_id: int, usuario: models.Usuario = Depends(requer_papel("admin", "analista")), db: Session = Depends(get_db)):
    rotina = db.query(models.Rotina).get(rotina_id)
    if not rotina:
        raise HTTPException(404, "Rotina não encontrada.")
    db.query(models.ExecucaoRotina).filter(models.ExecucaoRotina.rotina_id == rotina_id).delete()
    db.delete(rotina)
    registrar_log(db, usuario.username, "excluir_rotina", entidade="rotina", entidade_id=rotina_id)
    db.commit()
    return {"ok": True}


def _dias_esperados(rotina: models.Rotina, data_inicio: date, data_fim: date) -> list:
    """Quais datas, dentro do período, essa rotina deveria ter sido
    executada - hoje só "diaria" tem regra definida (todo dia corrido).
    "semanal"/"mensal" não geram cobrança de execução ainda (ver
    docstring do módulo)."""
    if rotina.frequencia != "diaria":
        return []
    dias = []
    d = data_inicio
    while d <= data_fim:
        dias.append(d)
        d += timedelta(days=1)
    return dias


@router.get("/execucoes", response_model=list[schemas.ExecucaoRotinaOut])
def listar_execucoes(
    data_inicio: date = Query(...),
    data_fim: date = Query(...),
    setor: Optional[str] = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """Retorna uma linha por (rotina diária ativa × dia esperado) no
    período - usando o registro real em ExecucaoRotina quando existe, ou
    uma linha "Pendente" virtual (não persistida) quando ainda não foi
    marcada. Isso permite à tela mostrar o checklist completo do período
    sem precisar de um job separado criando execuções antecipadamente."""
    q = db.query(models.Rotina).filter(models.Rotina.ativo.is_(True))
    if setor:
        q = q.filter(models.Rotina.setor == setor)
    rotinas = q.all()

    if not rotinas:
        return []

    existentes = {
        (e.rotina_id, e.data_referencia): e
        for e in db.query(models.ExecucaoRotina).filter(
            models.ExecucaoRotina.data_referencia >= data_inicio, models.ExecucaoRotina.data_referencia <= data_fim,
            models.ExecucaoRotina.rotina_id.in_([r.id for r in rotinas]),
        ).all()
    }

    hoje = date.today()
    resultado = []
    for rotina in rotinas:
        for dia in _dias_esperados(rotina, data_inicio, data_fim):
            existente = existentes.get((rotina.id, dia))
            if existente:
                item = schemas.ExecucaoRotinaOut.model_validate(existente).model_dump()
            else:
                # dia passado e nunca marcado = Atrasada; dia de hoje/futuro ainda não marcado = Pendente
                status_virtual = "Atrasada" if dia < hoje else "Pendente"
                item = {
                    "id": None, "rotina_id": rotina.id, "rotina_nome": None, "rotina_setor": None,
                    "data_referencia": dia, "status": status_virtual, "concluido_em": None,
                    "concluido_por": None, "observacao": None,
                }
            item["rotina_nome"] = rotina.nome
            item["rotina_setor"] = rotina.setor
            resultado.append(item)

    resultado.sort(key=lambda x: (str(x["data_referencia"]), x["rotina_nome"] or ""))
    return resultado


@router.patch("/{rotina_id}/execucoes/{data_referencia}", response_model=schemas.ExecucaoRotinaOut)
def marcar_execucao(
    rotina_id: int, data_referencia: date, payload: schemas.ExecucaoRotinaAtualizar,
    usuario: models.Usuario = Depends(obter_usuario_atual), db: Session = Depends(get_db),
):
    """Upsert - cria a ExecucaoRotina na hora se ainda não existir (o
    endpoint de listagem só devolve uma linha virtual até aqui, pra não
    precisar de um job noturno pré-criando linha por linha)."""
    if payload.status not in ("Pendente", "Concluida", "Atrasada", "Nao_Aplicavel"):
        raise HTTPException(400, "Status inválido. Use: Pendente, Concluida, Atrasada ou Nao_Aplicavel.")
    rotina = db.query(models.Rotina).get(rotina_id)
    if not rotina:
        raise HTTPException(404, "Rotina não encontrada.")

    execucao = db.query(models.ExecucaoRotina).filter_by(rotina_id=rotina_id, data_referencia=data_referencia).first()
    if not execucao:
        execucao = models.ExecucaoRotina(rotina_id=rotina_id, data_referencia=data_referencia)
        db.add(execucao)

    execucao.status = payload.status
    execucao.observacao = payload.observacao
    if payload.status == "Concluida":
        execucao.concluido_em = datetime.utcnow()
        execucao.concluido_por = usuario.nome_exibicao or usuario.username
    else:
        execucao.concluido_em = None
        execucao.concluido_por = None

    registrar_log(db, usuario.username, "marcar_execucao_rotina", entidade="rotina", entidade_id=rotina_id,
                  detalhes={"data_referencia": str(data_referencia), "status": payload.status})
    db.commit()
    db.refresh(execucao)
    resultado = schemas.ExecucaoRotinaOut.model_validate(execucao).model_dump()
    resultado["rotina_nome"] = rotina.nome
    resultado["rotina_setor"] = rotina.setor
    return resultado


@router.get("/dashboard/cumprimento")
def dashboard_cumprimento(
    data_inicio: date = Query(...),
    data_fim: date = Query(...),
    setor: Optional[str] = None,
    usuario: models.Usuario = Depends(obter_usuario_atual),
    db: Session = Depends(get_db),
):
    """% de cumprimento geral (Concluida / (Concluida + Atrasada), ou
    seja, das rotinas cujo prazo já passou ou foi cumprido - "Pendente"
    de dias futuros não entra no denominador, senão o % ficaria
    artificialmente baixo só porque o dia ainda não terminou) - mesma
    métrica do "Cumprimento Geral de Rotinas" do MBR (slide 25), com
    quebra por setor."""
    execucoes = listar_execucoes(data_inicio=data_inicio, data_fim=data_fim, setor=setor, usuario=usuario, db=db)

    from collections import defaultdict
    por_setor = defaultdict(lambda: {"concluidas": 0, "atrasadas": 0, "pendentes": 0, "nao_aplicavel": 0})
    for e in execucoes:
        chave = e["rotina_setor"] or "Sem setor"
        if e["status"] == "Concluida":
            por_setor[chave]["concluidas"] += 1
        elif e["status"] == "Atrasada":
            por_setor[chave]["atrasadas"] += 1
        elif e["status"] == "Nao_Aplicavel":
            por_setor[chave]["nao_aplicavel"] += 1
        else:
            por_setor[chave]["pendentes"] += 1

    def pct(v):
        esperado = v["concluidas"] + v["atrasadas"]
        return round(v["concluidas"] / esperado * 100, 2) if esperado else None

    total = {"concluidas": 0, "atrasadas": 0, "pendentes": 0, "nao_aplicavel": 0}
    for v in por_setor.values():
        for k in total:
            total[k] += v[k]
    total_esperado = total["concluidas"] + total["atrasadas"]

    return {
        "periodo": {"data_inicio": str(data_inicio), "data_fim": str(data_fim)},
        "total_esperado": total_esperado,
        "total_concluidas": total["concluidas"],
        "total_atrasadas": total["atrasadas"],
        "total_pendentes": total["pendentes"],
        "cumprimento_geral_pct": round(total["concluidas"] / total_esperado * 100, 2) if total_esperado else None,
        "por_setor": [
            {"setor": s, "concluidas": v["concluidas"], "atrasadas": v["atrasadas"], "pendentes": v["pendentes"], "cumprimento_pct": pct(v)}
            for s, v in sorted(por_setor.items())
        ],
    }
