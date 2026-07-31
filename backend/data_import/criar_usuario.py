"""
Cria um usuário novo ou reseta a senha de um usuário existente, direto no
banco - útil se todo mundo perder acesso e precisar recuperar sem passar
pela API/tela de login. Também limpa bloqueio por tentativas de senha
erradas, caso a conta tenha ficado bloqueada.

Uso:
    python -m data_import.criar_usuario --username joao --senha "SenhaForte123" --papel analista
    python -m data_import.criar_usuario --username admin --senha "NovaSenha456"   # reseta senha de quem já existe
"""
import argparse
import os
from app.database import SessionLocal, Base, engine, DATABASE_URL
from app import models
from app.auth import hash_senha

Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--senha", required=True)
    parser.add_argument("--papel", default="leitura", choices=["admin", "analista", "leitura"])
    parser.add_argument("--nome", default=None)
    args = parser.parse_args()

    print(f"Banco usado: {DATABASE_URL}")
    if DATABASE_URL.startswith("sqlite"):
        caminho_arquivo = DATABASE_URL.replace("sqlite:///", "")
        if os.path.exists(caminho_arquivo):
            print(f"Arquivo: {os.path.abspath(caminho_arquivo)} ({os.path.getsize(caminho_arquivo) / 1024:.0f} KB)")
        else:
            print("ATENÇÃO: esse arquivo de banco ainda não existe - será criado agora, do zero (vazio).")

    db = SessionLocal()
    total_fechamentos = db.query(models.FechamentoInventario).count()
    print(f"Fechamentos de inventário encontrados neste banco: {total_fechamentos}")

    usuario = db.query(models.Usuario).filter_by(username=args.username).first()
    if usuario:
        usuario.senha_hash = hash_senha(args.senha)
        usuario.papel = args.papel
        usuario.ativo = True
        usuario.tentativas_falhas = 0
        usuario.bloqueado_ate = None
        print(f"Senha, papel e bloqueio de '{args.username}' resetados (papel: {args.papel}).")
    else:
        db.add(models.Usuario(
            username=args.username, nome_exibicao=args.nome,
            senha_hash=hash_senha(args.senha), papel=args.papel, ativo=True,
        ))
        print(f"Usuário '{args.username}' criado (papel: {args.papel}).")
    db.commit()
    db.close()
