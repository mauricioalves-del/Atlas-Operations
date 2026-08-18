"""
Outros Dashboards (20/08/2026, ampliado em 18/08/2026 com indicadores
dinâmicos) - dashboards HTML autocontidos que a equipe já mantém em paralelo
ao Atlas, fora dos módulos nativos do sistema. Nasceu da conversa sobre o
slide de FEFO do MBR: a "quebra de FEFO" que o Atlas calcula a partir da data
da transferência não reflete disponibilidade real medida no momento (ver
docstring de ../fefo.py) - em vez de forçar essa métrica dentro do relatório,
o admin sobe aqui o HTML já pronto de cada dashboard que já existe por fora,
e ele fica acessível dentro do Atlas, embutido via iframe.

5 slots fixos (SLOTS abaixo) + indicadores dinâmicos (pedido do usuário,
18/08/2026: "adicione a opção de adicionar mais indicadores e adicionar
automaticamente na construção do MBR"). Os 5 fixos têm slide dedicado no MBR
(FEFO e Testes Industriais filtram pelo mês; os outros 3 entram como retrato
datado - ver mbr_generator.py). Qualquer indicador criado aqui pelo admin
(POST "") entra automaticamente como um slide adicional na seção "Outros" do
MBR, com extração GENÉRICA (tabelas + filtros do cabeçalho de exportação, se
houver - ver dashboards_externos_extrator.extrair_generico): não tenta
adivinhar KPIs de layout/CSS específico de cada exportação (arriscado herdar
uma leitura errada de um layout desconhecido) - só usa o que dá pra ler com
confiança de qualquer HTML: as tabelas de verdade que ele contém.
"""
import re
import unicodedata
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import requer_papel
from ..audit import registrar_log

router = APIRouter(prefix="/dashboards-externos", tags=["dashboards_externos"])

SLOTS = [
    ("controle_fefo", "Controle de FEFO"),
    ("farol_shelf_life", "Farol de Shelf-Life"),
    ("recuperacao_shelf", "Recuperação de Shelf"),
    ("testes_industriais", "Testes Industriais"),
    ("baixas_operacionais", "Dashboard Baixas Operacionais"),
]
NOME_POR_CHAVE = dict(SLOTS)
CHAVES_VALIDAS = set(NOME_POR_CHAVE)


def _slugificar(nome: str) -> str:
    """'Farol de Shelf-Life' -> 'farol_de_shelf_life' - só letras/números
    ASCII e underscore, pra virar uma chave estável e legível em log/URL."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")
    return slug or "indicador"


class NovoIndicador(BaseModel):
    nome_exibicao: str


@router.get("")
def listar_dashboards_externos(usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    """Status dos 5 slots fixos + qualquer indicador dinâmico já criado -
    não devolve o HTML em si (pode ser grande demais pra uma listagem), só
    quem/quando enviou. O conteúdo é buscado sob demanda em GET
    /{chave}/conteudo, quando a pessoa clica em "Abrir". "enviado" checa
    html_content não vazio (não só a existência da linha) porque um
    indicador dinâmico recém-criado já tem uma linha no banco antes de
    receber o primeiro arquivo (ver POST "" abaixo)."""
    existentes = {d.chave: d for d in db.query(models.DashboardExterno).all()}

    def _linha(chave, nome, personalizado):
        d = existentes.get(chave)
        enviado = bool(d and d.html_content)
        return {
            "chave": chave,
            "nome_exibicao": nome,
            "enviado": enviado,
            "personalizado": personalizado,
            "enviado_por": d.enviado_por if d else None,
            "enviado_em": d.enviado_em.isoformat() if (d and d.enviado_em and enviado) else None,
            "nome_arquivo_original": d.nome_arquivo_original if d else None,
        }

    fixos = [_linha(chave, nome, False) for chave, nome in SLOTS]
    dinamicos = [
        _linha(d.chave, d.nome_exibicao, True)
        for d in existentes.values()
        if d.chave not in CHAVES_VALIDAS
    ]
    dinamicos.sort(key=lambda item: item["nome_exibicao"].lower())
    return fixos + dinamicos


@router.post("")
def criar_indicador_dinamico(
    payload: NovoIndicador,
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    """Cria um novo slot de indicador (pedido do usuário, 18/08/2026) - só o
    nome de exibição, sem arquivo ainda (a pessoa sobe o .html depois, pelo
    mesmo botão "Enviar .html" que os 5 fixos já usam). A chave é gerada a
    partir do nome (slug) com sufixo "_2", "_3"... se colidir com algo que já
    existe, pra nunca sobrescrever por engano um indicador (fixo ou
    dinâmico) que já tem esse slug."""
    nome = (payload.nome_exibicao or "").strip()
    if not nome:
        raise HTTPException(400, "Informe um nome pro indicador.")
    if len(nome) > 80:
        raise HTTPException(400, "Nome muito longo (máximo 80 caracteres).")

    base = _slugificar(nome)
    chave = base
    sufixo = 2
    chaves_em_uso = CHAVES_VALIDAS | {d.chave for d in db.query(models.DashboardExterno.chave).all()}
    while chave in chaves_em_uso:
        chave = f"{base}_{sufixo}"
        sufixo += 1

    db.add(models.DashboardExterno(
        chave=chave, nome_exibicao=nome, html_content="",
        enviado_por=None, enviado_em=None,
    ))
    registrar_log(db, usuario.username, "criar_dashboard_externo", entidade="dashboard_externo", entidade_id=chave,
                  detalhes={"nome_exibicao": nome})
    db.commit()
    return {"ok": True, "chave": chave, "nome_exibicao": nome}


@router.post("/{chave}/upload")
async def enviar_dashboard_externo(
    chave: str,
    arquivo: UploadFile = File(...),
    usuario: models.Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    """Recebe um .html autocontido (CSS/JS já embutidos - nada de referência
    a arquivo externo, já que o Atlas só guarda esse único arquivo) e
    substitui o conteúdo anterior do mesmo slot, se houver (upsert por
    chave). Slots fixos (SLOTS) fazem upsert direto; um indicador dinâmico
    precisa ter sido criado antes via POST "" - não aceita subir um arquivo
    pra uma chave que nunca foi registrada, pra não deixar o admin criar
    indicadores "invisíveis" (sem nome_exibicao) por engano."""
    existente = db.query(models.DashboardExterno).filter_by(chave=chave).first()
    if chave not in CHAVES_VALIDAS and not existente:
        raise HTTPException(404, f"Indicador desconhecido: '{chave}'. Crie o indicador primeiro em Outros Dashboards > Adicionar Indicador.")
    if not arquivo.filename or not arquivo.filename.lower().endswith((".html", ".htm")):
        raise HTTPException(400, "Envie um arquivo .html (autocontido - CSS e JS já embutidos no próprio arquivo).")

    conteudo_bruto = await arquivo.read()
    try:
        html = conteudo_bruto.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Não consegui ler o arquivo como texto UTF-8. Salve o .html com essa codificação e tente de novo.")

    if existente:
        existente.html_content = html
        existente.nome_arquivo_original = arquivo.filename
        existente.enviado_por = usuario.username
        existente.enviado_em = datetime.utcnow()
    else:
        db.add(models.DashboardExterno(
            chave=chave, nome_exibicao=NOME_POR_CHAVE[chave], html_content=html,
            nome_arquivo_original=arquivo.filename, enviado_por=usuario.username,
        ))

    registrar_log(
        db, usuario.username, "enviar_dashboard_externo", entidade="dashboard_externo", entidade_id=chave,
        detalhes={"arquivo": arquivo.filename, "tamanho_bytes": len(conteudo_bruto)},
    )
    db.commit()
    return {"ok": True, "chave": chave}


@router.get("/{chave}/conteudo")
def conteudo_dashboard_externo(chave: str, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    """HTML bruto do dashboard, pra ser embutido via iframe (srcdoc) no
    front-end. Devolvido por um fetch autenticado, não por navegação direta
    do navegador - uma tag <iframe src="..."> comum não manda o cabeçalho de
    autorização, então o front busca aqui com o token e injeta o resultado
    no iframe via srcdoc."""
    d = db.query(models.DashboardExterno).filter_by(chave=chave).first()
    if not d or not d.html_content:
        raise HTTPException(404, "Esse dashboard ainda não teve nenhum arquivo enviado.")
    return Response(content=d.html_content, media_type="text/html")


@router.delete("/{chave}")
def remover_dashboard_externo(chave: str, usuario: models.Usuario = Depends(requer_papel("admin")), db: Session = Depends(get_db)):
    """Pra um slot fixo (SLOTS), remove só o conteúdo enviado - o slot
    continua existindo na lista (volta a aparecer como "Vazio"), porque a
    lista de fixos vem de SLOTS, não do banco. Pra um indicador dinâmico,
    remove o indicador por completo (ele só existe no banco - sem a linha,
    desaparece da lista)."""
    d = db.query(models.DashboardExterno).filter_by(chave=chave).first()
    if not d:
        raise HTTPException(404, "Esse indicador não existe ou ainda não teve nenhum arquivo enviado.")
    db.delete(d)
    registrar_log(db, usuario.username, "remover_dashboard_externo", entidade="dashboard_externo", entidade_id=chave)
    db.commit()
    return {"ok": True}
