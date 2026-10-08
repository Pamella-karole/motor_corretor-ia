import sqlite3
import hashlib
import random
import string
import pandas as pd
from datetime import datetime

DB_NAME = "motor_corretor.db"

def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    # Garante que as regras ON DELETE CASCADE declaradas no esquema sejam
    # aplicadas em todas as conexões, inclusive em bancos já existentes.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode('utf-8')).hexdigest()

def init_db():
    """Inicializa as tabelas do banco de dados e cria contas de teste."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Tabela de Usuários (Professores, Alunos e Admin)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL,      -- RA para aluno, E-mail para professor/admin
            nome TEXT NOT NULL,
            senha TEXT NOT NULL,
            role TEXT NOT NULL,              -- 'aluno', 'professor', 'admin'
            turma TEXT,                      -- Ex: '3º A Adm' (apenas para alunos)
            trocar_senha INTEGER DEFAULT 0
        );
        """)
        
        # Tabela de Tarefas
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tarefas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,     -- Ex: COD-9842
            titulo TEXT NOT NULL,
            enunciado TEXT NOT NULL,
            gabarito TEXT NOT NULL,
            professor_id INTEGER NOT NULL,
            data_criacao DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (professor_id) REFERENCES usuarios (id)
        );
        """)
        
        # Tabela de Critérios de Avaliação (Rubricas)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS criterios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tarefa_id INTEGER NOT NULL,
            descricao TEXT NOT NULL,
            peso REAL NOT NULL,
            FOREIGN KEY (tarefa_id) REFERENCES tarefas (id) ON DELETE CASCADE
        );
        """)
        
        # Tabela de Envios e Tentativas
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS envios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tarefa_id INTEGER NOT NULL,
            aluno_id INTEGER NOT NULL,
            tentativa INTEGER NOT NULL,
            nota REAL NOT NULL,
            parecer TEXT NOT NULL,
            data_envio DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tarefa_id) REFERENCES tarefas (id) ON DELETE CASCADE,
            FOREIGN KEY (aluno_id) REFERENCES usuarios (id) ON DELETE CASCADE
        );
        """)

        # Migração compatível com bancos criados antes do armazenamento dos
        # arquivos. ALTER TABLE é executado apenas quando a coluna ainda não
        # existe, preservando integralmente os envios antigos.
        cursor.execute("PRAGMA table_info(envios)")
        colunas_envios = {row[1] for row in cursor.fetchall()}
        if "arquivo_pdf" not in colunas_envios:
            cursor.execute("ALTER TABLE envios ADD COLUMN arquivo_pdf BLOB")
        if "nome_arquivo" not in colunas_envios:
            cursor.execute("ALTER TABLE envios ADD COLUMN nome_arquivo TEXT")
        if "mime_type" not in colunas_envios:
            cursor.execute("ALTER TABLE envios ADD COLUMN mime_type TEXT")
        
        # Carga Inicial de Teste
        cursor.execute("SELECT COUNT(*) FROM usuarios")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
            INSERT INTO usuarios (login, nome, senha, role, turma) 
            VALUES (?, ?, ?, ?, ?)
            """, ("admin@escola.com", "Administrador Geral", hash_senha("123456"), "admin", None))
            
            cursor.execute("""
            INSERT INTO usuarios (login, nome, senha, role, turma) 
            VALUES (?, ?, ?, ?, ?)
            """, ("prof@escola.com", "Professor Exemplo", hash_senha("123456"), "professor", None))
            
            cursor.execute("""
            INSERT INTO usuarios (login, nome, senha, role, turma) 
            VALUES (?, ?, ?, ?, ?)
            """, ("20260001", "Aluno Exemplo", hash_senha("123456"), "aluno", "3º A Adm"))
            
        conn.commit()

# --- AUTENTICAÇÃO E GESTÃO DE USUÁRIOS ---

def autenticar_usuario(login, senha):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM usuarios WHERE login = ? AND senha = ?",
            (login, hash_senha(senha))
        )
        user = cursor.fetchone()
        return dict(user) if user else None

def resetar_senha_aluno(ra, nova_senha="123456"):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE usuarios SET senha = ?, trocar_senha = 1 WHERE login = ? AND role = 'aluno'",
            (hash_senha(nova_senha), ra)
        )
        conn.commit()
        return cursor.rowcount > 0

def obter_turmas_cadastradas():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT turma FROM usuarios WHERE turma IS NOT NULL AND turma != '' ORDER BY turma")
        return [row["turma"] for row in cursor.fetchall()]

def obter_turmas_com_detalhes():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT turma, COUNT(*) as total_alunos 
        FROM usuarios 
        WHERE role = 'aluno' AND turma IS NOT NULL AND turma != ''
        GROUP BY turma 
        ORDER BY turma
        """)
        return [dict(row) for row in cursor.fetchall()]

def excluir_turma_e_alunos(nome_turma):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        DELETE FROM envios WHERE aluno_id IN (
            SELECT id FROM usuarios WHERE role = 'aluno' AND turma = ?
        )
        """, (nome_turma,))
        
        cursor.execute("DELETE FROM usuarios WHERE role = 'aluno' AND turma = ?", (nome_turma,))
        conn.commit()
        return cursor.rowcount

# --- GESTÃO DE TAREFAS ---

def gerar_codigo_unico():
    while True:
        num = ''.join(random.choices(string.digits, k=4))
        codigo = f"COD-{num}"
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tarefas WHERE codigo = ?", (codigo,))
            if not cursor.fetchone():
                return codigo

def criar_tarefa(titulo, enunciado, gabarito, professor_id, criterios_lista):
    codigo = gerar_codigo_unico()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO tarefas (codigo, titulo, enunciado, gabarito, professor_id)
        VALUES (?, ?, ?, ?, ?)
        """, (codigo, titulo, enunciado, gabarito, professor_id))
        
        tarefa_id = cursor.lastrowid
        
        for desc, peso in criterios_lista:
            cursor.execute("""
            INSERT INTO criterios (tarefa_id, descricao, peso)
            VALUES (?, ?, ?)
            """, (tarefa_id, desc, peso))
            
        conn.commit()
    return codigo

def obter_tarefa_por_codigo(codigo):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tarefas WHERE codigo = ?", (codigo.upper().strip(),))
        tarefa = cursor.fetchone()
        if not tarefa:
            return None
        
        tarefa_dict = dict(tarefa)
        cursor.execute("SELECT descricao, peso FROM criterios WHERE tarefa_id = ?", (tarefa_dict['id'],))
        tarefa_dict['criterios'] = cursor.fetchall()
        return tarefa_dict

def listar_tarefas_professor(professor_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tarefas WHERE professor_id = ? ORDER BY data_criacao DESC", (professor_id,))
        return [dict(row) for row in cursor.fetchall()]

def listar_todas_tarefas_admin():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT t.*, u.nome as professor_nome 
        FROM tarefas t 
        JOIN usuarios u ON t.professor_id = u.id 
        ORDER BY t.data_criacao DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

def excluir_tarefa_admin(codigo):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tarefas WHERE codigo = ?", (codigo.upper().strip(),))
        conn.commit()
        return cursor.rowcount > 0

# --- SUBMISSÕES E HISTÓRICO DE TENTATIVAS ---

def registrar_envio(
    tarefa_id,
    aluno_id,
    nota,
    parecer,
    arquivo_pdf=None,
    nome_arquivo=None,
    mime_type="application/pdf"
):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT MAX(tentativa) FROM envios WHERE tarefa_id = ? AND aluno_id = ?
        """, (tarefa_id, aluno_id))
        ultima = cursor.fetchone()[0]
        proxima_tentativa = (ultima or 0) + 1
        
        cursor.execute("""
        INSERT INTO envios (
            tarefa_id, aluno_id, tentativa, nota, parecer,
            arquivo_pdf, nome_arquivo, mime_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tarefa_id,
            aluno_id,
            proxima_tentativa,
            nota,
            parecer,
            arquivo_pdf,
            nome_arquivo,
            mime_type
        ))
        conn.commit()
        return proxima_tentativa

def obter_historico_aluno(tarefa_id, aluno_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT
            id,
            tentativa,
            nota,
            parecer,
            data_envio,
            nome_arquivo,
            mime_type,
            CASE WHEN arquivo_pdf IS NOT NULL THEN 1 ELSE 0 END AS possui_arquivo
        FROM envios 
        WHERE tarefa_id = ? AND aluno_id = ? 
        ORDER BY tentativa ASC
        """, (tarefa_id, aluno_id))
        return [dict(row) for row in cursor.fetchall()]

def obter_envio_por_id(envio_id):
    """Retorna uma tentativa, incluindo o PDF original armazenado."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT
            e.id,
            e.tarefa_id,
            e.aluno_id,
            e.tentativa,
            e.nota,
            e.parecer,
            e.data_envio,
            e.arquivo_pdf,
            e.nome_arquivo,
            e.mime_type,
            t.codigo AS tarefa_codigo,
            t.titulo AS tarefa_titulo,
            u.nome AS aluno_nome
        FROM envios e
        JOIN tarefas t ON t.id = e.tarefa_id
        JOIN usuarios u ON u.id = e.aluno_id
        WHERE e.id = ?
        """, (envio_id,))
        envio = cursor.fetchone()
        return dict(envio) if envio else None

def obter_envio_por_tentativa(tarefa_id, aluno_id, tentativa):
    """Retorna uma tentativa específica, incluindo o PDF original."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT
            e.id,
            e.tarefa_id,
            e.aluno_id,
            e.tentativa,
            e.nota,
            e.parecer,
            e.data_envio,
            e.arquivo_pdf,
            e.nome_arquivo,
            e.mime_type,
            t.codigo AS tarefa_codigo,
            t.titulo AS tarefa_titulo,
            u.nome AS aluno_nome
        FROM envios e
        JOIN tarefas t ON t.id = e.tarefa_id
        JOIN usuarios u ON u.id = e.aluno_id
        WHERE e.tarefa_id = ? AND e.aluno_id = ? AND e.tentativa = ?
        """, (tarefa_id, aluno_id, tentativa))
        envio = cursor.fetchone()
        return dict(envio) if envio else None

def obter_relatorio_tarefa_df(tarefa_id, turma_filtro=None):
    query = """
    SELECT 
        u.login AS RA,
        u.nome AS Aluno,
        u.turma AS Turma,
        e.tentativa AS Tentativa,
        e.nota AS Nota,
        e.parecer AS Parecer,
        e.data_envio AS Data_Envio
    FROM envios e
    JOIN usuarios u ON e.aluno_id = u.id
    WHERE e.tarefa_id = ?
    """
    params = [tarefa_id]
    
    if turma_filtro and turma_filtro != "Todas":
        query += " AND u.turma = ?"
        params.append(turma_filtro)
        
    query += " ORDER BY u.turma, u.nome, e.tentativa"
    
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df
