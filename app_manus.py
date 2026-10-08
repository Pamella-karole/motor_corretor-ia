import streamlit as st
import db
import pypdf
import docx
import google.generativeai as genai
import pandas as pd
import json
import io
import os
import re
from xml.sax.saxutils import escape as escape_xml
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Inicializa o banco de dados e as contas padrões
db.init_db()

st.set_page_config(page_title="Motor Corretor IA", page_icon="📝", layout="wide")

# Configuração segura da API Key da IA
try:
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "").strip()
except Exception:
    GEMINI_API_KEY = ""

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- CONTROLE DE SESSÃO ---
if "user" not in st.session_state:
    st.session_state.user = None

def extrair_texto_pdf(arquivo_pdf):
    reader = pypdf.PdfReader(arquivo_pdf)
    texto = ""
    for page in reader.pages:
        texto += page.extract_text() or ""
    return texto.strip()

def extrair_texto_docx(arquivo_docx):
    doc = docx.Document(arquivo_docx)
    linhas = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n".join(linhas)

def gerar_pdf_corrigido(
    arquivo_original,
    titulo_atividade,
    nome_aluno,
    tentativa,
    nota,
    parecer,
    data_envio
):
    """Anexa uma página formatada de correção ao PDF enviado pelo aluno."""
    if not arquivo_original:
        raise ValueError("O PDF original desta tentativa não está disponível.")

    original_stream = io.BytesIO(arquivo_original)
    leitor_original = pypdf.PdfReader(original_stream)

    if leitor_original.is_encrypted:
        resultado = leitor_original.decrypt("")
        if not resultado:
            raise ValueError("O PDF original está protegido por senha e não pode ser combinado.")

    estilos = getSampleStyleSheet()
    estilos.add(ParagraphStyle(
        name="TituloCorrecao",
        parent=estilos["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1F4E79"),
        spaceAfter=18,
    ))
    estilos.add(ParagraphStyle(
        name="CabecalhoCorrecao",
        parent=estilos["Heading2"],
        textColor=colors.HexColor("#1F4E79"),
        spaceBefore=12,
        spaceAfter=8,
    ))
    estilos.add(ParagraphStyle(
        name="CorpoCorrecao",
        parent=estilos["BodyText"],
        fontSize=10.5,
        leading=15,
        spaceAfter=7,
    ))

    def texto_seguro(valor):
        return escape_xml(str(valor if valor is not None else "")).replace("\n", "<br/>")

    nota_formatada = f"{float(nota):.1f}%".replace(".", ",")
    dados_identificacao = [
        [Paragraph("<b>Atividade</b>", estilos["CorpoCorrecao"]), Paragraph(texto_seguro(titulo_atividade), estilos["CorpoCorrecao"])],
        [Paragraph("<b>Aluno</b>", estilos["CorpoCorrecao"]), Paragraph(texto_seguro(nome_aluno), estilos["CorpoCorrecao"])],
        [Paragraph("<b>Tentativa</b>", estilos["CorpoCorrecao"]), Paragraph(texto_seguro(tentativa), estilos["CorpoCorrecao"])],
        [Paragraph("<b>Data do envio</b>", estilos["CorpoCorrecao"]), Paragraph(texto_seguro(data_envio), estilos["CorpoCorrecao"])],
    ]

    tabela = Table(dados_identificacao, colWidths=[4.2 * cm, 12.8 * cm])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF2F8")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#9FBAD0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C9D7E3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    nota_tabela = Table([
        [Paragraph("<b>Nota final</b>", estilos["CorpoCorrecao"]), Paragraph(f"<b>{nota_formatada}</b>", estilos["CorpoCorrecao"])],
    ], colWidths=[4.2 * cm, 12.8 * cm])
    nota_tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E8F5E9")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#5B9B68")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))

    historia = [
        Paragraph("Correção da Atividade", estilos["TituloCorrecao"]),
        tabela,
        Spacer(1, 12),
        nota_tabela,
        Paragraph("Parecer do Corretor", estilos["CabecalhoCorrecao"]),
    ]

    parecer_linhas = str(parecer or "Sem parecer disponível.").splitlines()
    if not parecer_linhas:
        parecer_linhas = ["Sem parecer disponível."]
    for linha in parecer_linhas:
        historia.append(Paragraph(texto_seguro(linha) or "&nbsp;", estilos["CorpoCorrecao"]))

    correcao_stream = io.BytesIO()
    documento = SimpleDocTemplate(
        correcao_stream,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=f"Correção - {titulo_atividade}",
        author="Motor Corretor IA",
    )

    def adicionar_rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawRightString(A4[0] - 2 * cm, 1 * cm, f"Página {doc.page}")
        canvas.restoreState()

    documento.build(historia, onFirstPage=adicionar_rodape, onLaterPages=adicionar_rodape)

    leitor_correcao = pypdf.PdfReader(io.BytesIO(correcao_stream.getvalue()))
    escritor = pypdf.PdfWriter()
    for pagina in leitor_original.pages:
        escritor.add_page(pagina)
    for pagina in leitor_correcao.pages:
        escritor.add_page(pagina)

    escritor.add_metadata({
        "/Title": f"Resposta com correção - {titulo_atividade}",
        "/Author": "Motor Corretor IA",
        "/Subject": "Resposta do aluno acrescida da correção do sistema",
    })

    resultado_stream = io.BytesIO()
    escritor.write(resultado_stream)
    return resultado_stream.getvalue()

def nome_pdf_corrigido(nome_original, tentativa):
    """Gera um nome seguro e legível para o arquivo disponibilizado."""
    nome_base = os.path.splitext(os.path.basename(nome_original or "resposta"))[0]
    nome_base = re.sub(r"[^\w\-]+", "_", nome_base, flags=re.UNICODE).strip("_")
    nome_base = nome_base or "resposta"
    return f"{nome_base}_com_correcao_tentativa_{tentativa}.pdf"

def chamar_gemini_json(prompt):
    """Consulta os modelos ativos diretamente no Google AI Studio e envia a requisição."""
    if not GEMINI_API_KEY or GEMINI_API_KEY in ["", "SUA_CHAVE_AQUI"]:
        return None, "Chave da API do Gemini não configurada em .streamlit/secrets.toml."

    # 1. Consulta dinamicamente os modelos habilitados para a sua chave
    modelos_validos = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                modelos_validos.append(m.name)
    except Exception as e:
        return None, f"Erro ao consultar modelos da conta: {str(e)}"

    if not modelos_validos:
        return None, "Nenhum modelo de geração de texto foi liberado para esta chave de API."

    # Prioriza modelos da família 'flash' na lista retornada
    modelos_ordenados = sorted(modelos_validos, key=lambda x: 0 if 'flash' in x.lower() else 1)

    ultimo_erro = None
    for nome_modelo in modelos_ordenados:
        try:
            model = genai.GenerativeModel(nome_modelo)
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            dados = json.loads(response.text)
            return dados, None
        except Exception as e:
            ultimo_erro = str(e)
            continue

    return None, f"Erro na chamada da IA (modelos testados: {', '.join(modelos_ordenados[:2])}): {ultimo_erro}"

def processar_docx_com_gemini(texto_docx):
    prompt = f"""
    Você é um assistente pedagógico. Analise o texto extraído de um formulário de atividade em Word (.docx).
    
    TEXTO DO FORMULÁRIO:
    {texto_docx}
    
    Extraia e identifique os campos exigidos e responda ESTRITAMENTE em formato JSON com a seguinte estrutura:
    {{
        "titulo": "Título ou nome da atividade",
        "enunciado": "Enunciado completo da atividade/questão",
        "gabarito": "Gabarito oficial ou resposta esperada",
        "criterios": [
            {{"descricao": "Descrição do critério 1", "peso": 5.0}},
            {{"descricao": "Descrição do critério 2", "peso": 5.0}}
        ]
    }}
    """
    dados, erro = chamar_gemini_json(prompt)
    if erro:
        if "API_KEY_INVALID" in erro or "API key not valid" in erro:
            return None, "A chave da API do Gemini no .streamlit/secrets.toml é inválida."
        return None, f"Erro ao processar o documento com a IA: {erro}"
    return dados, None

def avaliar_com_gemini(enunciado, gabarito, criterios, texto_aluno):
    criterios_str = "\n".join([f"- {desc} (Peso: {peso})" for desc, peso in criterios])
    
    prompt = f"""
    Você é um corretor pedagógico rigoroso e justo.
    
    [ENUNCIADO DA ATIVIDADE]
    {enunciado}
    
    [GABARITO / RESPOSTA ESPERADA]
    {gabarito}
    
    [CRITÉRIOS DE AVALIAÇÃO]
    {criterios_str}
    
    [RESPOSTA DO ALUNO]
    {texto_aluno}
    
    INSTRUÇÕES:
    1. Avalie a resposta do aluno em comparação direta com o Gabarito e os Critérios.
    2. Atribua uma Nota Final de 0 a 100.
    3. Escreva um parecer justificando a nota, apontando pontos fortes e o que precisa ser corrigido.
    4. Responda ESTRITAMENTE em formato JSON com as chaves: "nota" (número de 0 a 100) e "parecer" (texto explicativo).
    """

    dados, erro = chamar_gemini_json(prompt)
    if erro:
        if "API_KEY_INVALID" in erro or "API key not valid" in erro:
            return 0.0, "Erro: A chave da API do Gemini no .streamlit/secrets.toml é inválida."
        return 0.0, f"Erro ao processar resposta da IA: {erro}"

    return float(dados.get("nota", 0.0)), dados.get("parecer", "Sem parecer disponível.")

# ==========================================
# TELA DE LOGIN
# ==========================================
if not st.session_state.user:
    st.title("📝 Motor Corretor - Acesso")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Login no Sistema")
        login_input = st.text_input("RA (Aluno) ou E-mail (Professor/Admin)")
        senha_input = st.text_input("Senha", type="password")
        
        if st.button("Entrar", type="primary"):
            user = db.autenticar_usuario(login_input.strip(), senha_input.strip())
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Login ou senha inválidos.")
    st.stop()

# --- BARRA LATERAL ---
user = st.session_state.user
role_usuario = str(user.get("role", "")).strip().lower()

st.sidebar.write(f"👤 **{user['nome']}**")

texto_turma = f" | {user['turma']}" if user.get("turma") else ""
st.sidebar.caption(f"Perfil: **{role_usuario.capitalize()}**{texto_turma}")

if st.sidebar.button("Sair"):
    st.session_state.user = None
    st.rerun()

# ==========================================
# PAINEL DO ALUNO
# ==========================================
if role_usuario == "aluno":
    st.title("🚀 Enviar Atividade para Correção")
    
    cod_input = st.text_input("Código da Atividade (fornecido pelo professor no Classroom):", placeholder="Ex: COD-1234")
    
    if cod_input:
        tarefa = db.obter_tarefa_por_codigo(cod_input)
        if not tarefa:
            st.warning("Código de atividade não encontrado. Verifique com seu professor.")
        else:
            st.success(f"Atividade Encontrada: **{tarefa['titulo']}**")
            
            with st.expander("📌 Ver Enunciado e Critérios de Avaliação"):
                st.write("**Enunciado:**", tarefa["enunciado"])
                st.write("**Critérios:**")
                for c_desc, c_peso in tarefa["criterios"]:
                    st.write(f"- {c_desc} *(Peso: {c_peso})*")
            
            historico = db.obter_historico_aluno(tarefa["id"], user["id"])
            if historico:
                st.subheader("📊 Seu Histórico de Tentativas")
                for h in historico:
                    st.info(f"**Tentativa {h['tentativa']}** - Nota: **{h['nota']:.1f}%** | Data: {h['data_envio']}\n\n*Parecer:* {h['parecer']}")

                    if h.get("possui_arquivo"):
                        envio = db.obter_envio_por_id(h["id"])
                        if envio and envio.get("arquivo_pdf"):
                            try:
                                pdf_corrigido = gerar_pdf_corrigido(
                                    envio["arquivo_pdf"],
                                    envio["tarefa_titulo"],
                                    envio["aluno_nome"],
                                    envio["tentativa"],
                                    envio["nota"],
                                    envio["parecer"],
                                    envio["data_envio"],
                                )
                                st.download_button(
                                    label=f"📥 Baixar resposta com correção — Tentativa {h['tentativa']}",
                                    data=pdf_corrigido,
                                    file_name=nome_pdf_corrigido(h.get("nome_arquivo"), h["tentativa"]),
                                    mime="application/pdf",
                                    key=f"download_correcao_{h['id']}",
                                )
                            except Exception as erro_pdf:
                                st.warning(f"Não foi possível gerar o PDF corrigido desta tentativa: {erro_pdf}")
                    else:
                        st.caption("O arquivo original desta tentativa não está disponível para download.")
            
            st.divider()
            st.subheader("📤 Nova Submissão")
            arquivo_pdf = st.file_uploader("Envie sua resposta em arquivo PDF", type=["pdf"])
            
            if arquivo_pdf and st.button("Submeter para Correção Instantânea", type="primary"):
                with st.spinner("O Motor Corretor está analisando sua resposta com IA..."):
                    pdf_bytes = arquivo_pdf.getvalue()
                    limite_pdf = 10 * 1024 * 1024

                    if len(pdf_bytes) > limite_pdf:
                        st.error("O PDF excede o limite de 10 MB permitido para armazenamento.")
                    else:
                        try:
                            texto_aluno = extrair_texto_pdf(io.BytesIO(pdf_bytes))
                        except Exception as erro_pdf:
                            st.error(f"Não foi possível ler o PDF enviado. Verifique se o arquivo não está corrompido: {erro_pdf}")
                            texto_aluno = ""

                        if not texto_aluno:
                            st.error("Não foi possível extrair texto deste PDF. Certifique-se de que não é um documento digitalizado/imagem.")
                        else:
                            nota, parecer = avaliar_com_gemini(
                                tarefa["enunciado"],
                                tarefa["gabarito"],
                                tarefa["criterios"],
                                texto_aluno
                            )

                            tentativa_num = db.registrar_envio(
                                tarefa["id"],
                                user["id"],
                                nota,
                                parecer,
                                arquivo_pdf=pdf_bytes,
                                nome_arquivo=arquivo_pdf.name,
                                mime_type=arquivo_pdf.type or "application/pdf",
                            )

                            st.balloons()
                            st.success(f"Atividade avaliada! Tentativa #{tentativa_num} registrada.")
                            st.metric("Nota Obtida", f"{nota:.1f}%")
                            st.write("**Parecer do Corretor:**")
                            st.info(parecer)

                            envio_salvo = db.obter_envio_por_tentativa(
                                tarefa["id"], user["id"], tentativa_num
                            )
                            if envio_salvo and envio_salvo.get("arquivo_pdf"):
                                try:
                                    pdf_corrigido = gerar_pdf_corrigido(
                                        envio_salvo["arquivo_pdf"],
                                        envio_salvo["tarefa_titulo"],
                                        envio_salvo["aluno_nome"],
                                        envio_salvo["tentativa"],
                                        envio_salvo["nota"],
                                        envio_salvo["parecer"],
                                        envio_salvo["data_envio"],
                                    )
                                    st.download_button(
                                        label="📥 Baixar minha resposta com a correção",
                                        data=pdf_corrigido,
                                        file_name=nome_pdf_corrigido(
                                            envio_salvo.get("nome_arquivo"),
                                            envio_salvo["tentativa"],
                                        ),
                                        mime="application/pdf",
                                        key=f"download_correcao_recente_{envio_salvo['id']}",
                                    )
                                except Exception as erro_pdf:
                                    st.warning(f"A tentativa foi salva, mas não foi possível gerar o PDF corrigido agora: {erro_pdf}")

# ==========================================
# PAINEL DO PROFESSOR
# ==========================================
elif role_usuario == "professor":
    st.title("👨‍🏫 Painel do Professor")
    
    tab1, tab2, tab3 = st.tabs([
        "📄 Upload de Atividade (.docx)", 
        "📊 Relatórios & Desempenho", 
        "🔑 Reset de Senhas"
    ])
    
    # TAB 1: CRIAR ATIVIDADE VIA DOCX
    with tab1:
        st.subheader("Nova Atividade via Formulário Word")
        st.info("💡 Suba o arquivo Word (.docx) contendo o Título, Enunciado, Gabarito e Critérios de Avaliação. A IA extrairá os dados automaticamente.")
        
        arquivo_docx = st.file_uploader("Selecione o arquivo da atividade (.docx)", type=["docx"])
        
        if arquivo_docx:
            if st.button("Analisar Documento e Extrair Atividade", type="primary"):
                with st.spinner("Processando arquivo Word e identificando critérios..."):
                    texto_docx = extrair_texto_docx(arquivo_docx)
                    if not texto_docx:
                        st.error("O arquivo Word enviado está vazio.")
                    else:
                        dados, erro = processar_docx_com_gemini(texto_docx)
                        if erro:
                            st.error(erro)
                        else:
                            st.session_state.dados_extraidos = dados
                            st.success("Documento lido com sucesso! Confira a pré-visualização abaixo:")

        if "dados_extraidos" in st.session_state and st.session_state.dados_extraidos:
            dados = st.session_state.dados_extraidos
            st.divider()
            st.subheader("📌 Pré-visualização da Atividade Extraída")
            
            st.write(f"**Título:** {dados.get('titulo')}")
            st.write(f"**Enunciado:** {dados.get('enunciado')}")
            st.write(f"**Gabarito:** {dados.get('gabarito')}")
            st.write("**Critérios / Rubricas:**")
            
            criterios_para_banco = []
            for c in dados.get("criterios", []):
                desc = c.get("descricao", "")
                peso = float(c.get("peso", 1.0))
                st.write(f"- {desc} *(Peso: {peso})*")
                criterios_para_banco.append((desc, peso))
            
            st.write("---")
            if st.button("Confirmar e Gerar Código da Atividade", type="primary"):
                cod_gerado = db.criar_tarefa(
                    dados.get("titulo"),
                    dados.get("enunciado"),
                    dados.get("gabarito"),
                    user["id"],
                    criterios_para_banco
                )
                st.balloons()
                st.success("Atividade cadastrada com sucesso!")
                st.code(cod_gerado, language="text")
                st.info("👉 Copie o código acima e compartilhe com os alunos no Google Classroom.")
                del st.session_state.dados_extraidos

    # TAB 2: RELATÓRIOS & EXPORTAÇÃO
    with tab2:
        st.subheader("Desempenho e Exportação por Atividade")
        tarefas = db.listar_tarefas_professor(user["id"])
        
        if not tarefas:
            st.info("Nenhuma atividade cadastrada por você ainda.")
        else:
            opcoes_tarefas = {f"{t['codigo']} - {t['titulo']}": t for t in tarefas}
            escolha = st.selectbox("Selecione a Atividade:", list(opcoes_tarefas.keys()))
            tarefa_sel = opcoes_tarefas[escolha]
            
            turmas_disp = ["Todas"] + db.obter_turmas_cadastradas()
            turma_filtro = st.selectbox("Filtrar por Turma:", turmas_disp)
            
            df_relatorio = db.obter_relatorio_tarefa_df(tarefa_sel["id"], turma_filtro)
            
            if df_relatorio.empty:
                st.warning("Nenhum envio registrado para esta atividade/turma ainda.")
            else:
                st.write(f"Exibindo **{len(df_relatorio)}** envios registrados:")
                st.dataframe(df_relatorio, use_container_width=True)
                
                csv = df_relatorio.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Baixar Planilha de Notas (CSV)",
                    data=csv,
                    file_name=f"Notas_{tarefa_sel['codigo']}_{turma_filtro}.csv",
                    mime="text/csv"
                )

    # TAB 3: RESET DE SENHAS
    with tab3:
        st.subheader("Gerenciamento de Acesso dos Alunos")
        ra_reset = st.text_input("Digite o RA do aluno que esqueceu a senha:")
        
        if st.button("Resetar Senha para '123456'"):
            if ra_reset:
                sucesso = db.resetar_senha_aluno(ra_reset.strip())
                if sucesso:
                    st.success(f"A senha do aluno RA {ra_reset} foi redefinida para '123456'.")
                else:
                    st.error("RA não encontrado ou não pertence a um aluno.")
            else:
                st.warning("Informe o RA do aluno.")

# ==========================================
# PAINEL DO ADMINISTRADOR
# ==========================================
elif role_usuario == "admin":
    st.title("🛡️ Painel do Administrador")
    
    tab_adm1, tab_adm2 = st.tabs([
        "🗑️ Excluir Atividades", 
        "🏫 Gerenciar & Excluir Turmas"
    ])
    
    # TAB 1 ADMIN: EXCLUIR ATIVIDADES
    with tab_adm1:
        st.subheader("Gestão de Atividades da Escola")
        st.warning("⚠️ O Administrador pode apagar qualquer atividade criada por qualquer professor. Esta ação remove todos os pareceres e histórico de notas do banco.")
        
        todas_tarefas = db.listar_todas_tarefas_admin()
        
        if not todas_tarefas:
            st.info("Nenhuma atividade encontrada no sistema.")
        else:
            st.write("**Atividades Ativas no Sistema:**")
            df_todas = pd.DataFrame(todas_tarefas)[['codigo', 'titulo', 'professor_nome', 'data_criacao']]
            df_todas.columns = ['Código', 'Título', 'Professor Responsável', 'Data de Criação']
            st.dataframe(df_todas, use_container_width=True)
            
            st.divider()
            cod_excluir = st.text_input("Digite o CÓDIGO EXATO da atividade para confirmar a exclusão (Ex: COD-1234):")
            
            if st.button("Excluir Atividade Definitivamente", type="primary"):
                if cod_excluir:
                    sucesso = db.excluir_tarefa_admin(cod_excluir)
                    if sucesso:
                        st.success(f"Atividade {cod_excluir.upper()} e todo seu histórico foram excluídos do banco de dados.")
                        st.rerun()
                    else:
                        st.error("Código de atividade não encontrado no sistema.")
                else:
                    st.warning("Digite o código da atividade para confirmar.")

    # TAB 2 ADMIN: GERENCIAR & EXCLUIR TURMAS
    with tab_adm2:
        st.subheader("Gestão e Limpeza de Turmas")
        st.warning("⚠️ Ao excluir uma turma, todos os alunos dessa turma e o seu histórico de entregas serão removidos do sistema.")
        
        turmas_detalhes = db.obter_turmas_com_detalhes()
        
        if not turmas_detalhes:
            st.info("Nenhuma turma registrada com alunos no momento.")
        else:
            df_turmas = pd.DataFrame(turmas_detalhes)
            df_turmas.columns = ['Nome da Turma', 'Alunos Cadastrados']
            st.dataframe(df_turmas, use_container_width=True)
            
            st.divider()
            turma_selecionada = st.selectbox("Selecione a turma que deseja remover:", [t['turma'] for t in turmas_detalhes])
            confirmacao_turma = st.text_input(f"Digite exatamente o nome da turma ('{turma_selecionada}') para confirmar a exclusão:")
            
            if st.button("Excluir Turma e Alunos Vinculados", type="primary"):
                if confirmacao_turma.strip() == turma_selecionada.strip():
                    total_removidos = db.excluir_turma_e_alunos(turma_selecionada)
                    st.success(f"A turma '{turma_selecionada}' e {total_removidos} registros de alunos associados foram excluídos com sucesso.")
                    st.rerun()
                else:
                    st.error("O nome digitado não coincide com a turma selecionada.")

else:
    st.error(f"Perfil de usuário '{user.get('role')}' não reconhecido.")
