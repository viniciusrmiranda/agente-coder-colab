import streamlit as st
import sqlite3
from groq import Groq
from duckduckgo_search import DDGS
import pypdf
import uuid
import re
import json
import numpy as np

# --- TENTAR IMPORTAR LETTA (opcional) ---
try:
    from letta_client import Letta
    LETTA_AVAILABLE = True
except ImportError:
    LETTA_AVAILABLE = False

st.set_page_config(page_title="Agente Coder", page_icon="🤖", layout="wide")

# --- AUTENTICAÇÃO COM GOOGLE ---
if not st.user.is_logged_in:
    st.title("🤖 Agente Coder")
    st.write("Faça login com sua conta do Google para acessar a aplicação.")
    if st.button("🔑 Entrar com o Google"):
        st.login("google")
    st.stop()

user_email = st.user.email

# --- TENTAR CARREGAR SENTENCE-TRANSFORMERS (fallback) ---
try:
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer('all-MiniLM-L6-v2')
    EMBEDDING_AVAILABLE = True
except Exception:
    EMBEDDING_AVAILABLE = False
    st.warning("⚠️ Embeddings não disponíveis. A busca semântica será limitada.")

# --- BANCO DE DADOS (histórico e memória local) ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS conversas 
                 (chat_id TEXT PRIMARY KEY, user_email TEXT, titulo TEXT, 
                  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, user_email TEXT, role TEXT, content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS memorias 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_email TEXT, fato TEXT, embedding TEXT, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def listar_conversas(email):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT chat_id, titulo FROM conversas WHERE user_email = ? ORDER BY criado_em DESC", (email,))
    rows = c.fetchall()
    conn.close()
    return rows

def criar_nova_conversa(email, titulo="Nova Conversa"):
    chat_id = str(uuid.uuid4())
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO conversas (chat_id, user_email, titulo) VALUES (?, ?, ?)", (chat_id, email, titulo))
    conn.commit()
    conn.close()
    return chat_id

def atualizar_titulo_conversa(chat_id, texto):
    titulo = texto[:30] + "..." if len(texto) > 30 else texto
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("UPDATE conversas SET titulo = ? WHERE chat_id = ? AND titulo = 'Nova Conversa'", (titulo, chat_id))
    conn.commit()
    conn.close()

def salvar_mensagem(chat_id, email, role, content):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO historico (chat_id, user_email, role, content) VALUES (?, ?, ?, ?)", (chat_id, email, role, content))
    conn.commit()
    conn.close()

def carregar_historico_chat(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM historico WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]

def deletar_conversa(chat_id):
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("DELETE FROM conversas WHERE chat_id = ?", (chat_id,))
    c.execute("DELETE FROM historico WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

# --- FUNÇÕES DE MEMÓRIA LOCAL (fallback) ---
def salvar_memoria_local(email, fato):
    """Salva um fato na memória local com embedding se disponível."""
    if not fato or len(fato) < 5:
        return
    embedding_json = None
    if EMBEDDING_AVAILABLE:
        try:
            embedding = embedder.encode(fato).tolist()
            embedding_json = json.dumps(embedding)
        except:
            pass
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("INSERT INTO memorias (user_email, fato, embedding) VALUES (?, ?, ?)", 
              (email, fato, embedding_json))
    conn.commit()
    conn.close()

def buscar_memorias_local(email, query, limit=3):
    """Busca memórias locais (fallback)."""
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute("SELECT fato FROM memorias WHERE user_email = ? ORDER BY criado_em DESC", (email,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        return []
    if EMBEDDING_AVAILABLE:
        try:
            # Busca semântica com embedding
            c.execute("SELECT id, fato, embedding FROM memorias WHERE user_email = ?", (email,))
            rows_full = c.fetchall()
            query_embedding = embedder.encode(query)
            resultados = []
            for id, fato, emb_json in rows_full:
                if emb_json:
                    emb = np.array(json.loads(emb_json))
                    sim = np.dot(query_embedding, emb) / (np.linalg.norm(query_embedding) * np.linalg.norm(emb) + 1e-8)
                    resultados.append((sim, fato))
            resultados.sort(key=lambda x: x[0], reverse=True)
            return [fato for _, fato in resultados[:limit]]
        except:
            pass
    # Fallback: busca por substring
    palavras = query.lower().split()
    if not palavras:
        return []
    condicoes = " OR ".join(["fato LIKE ?" for _ in palavras])
    params = [f"%{p}%" for p in palavras]
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    c.execute(f"SELECT fato FROM memorias WHERE user_email = ? AND ({condicoes}) ORDER BY criado_em DESC LIMIT ?", (email, *params, limit))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# --- INICIALIZAR LETTA (se disponível) ---
letta_api_key = st.secrets.get("LETTA_API_KEY")
if LETTA_AVAILABLE and letta_api_key:
    try:
        client = Letta(token=letta_api_key)
        # Nome do agente baseado no email do usuário
        AGENT_NAME = f"agente-coder-{user_email.replace('@', '-')}"
        # Buscar agente existente
        agentes = client.agents.list()
        agente_existente = None
        for a in agentes:
            if a.name == AGENT_NAME:
                agente_existente = a
                break
        if agente_existente:
            agent_id = agente_existente.id
            st.sidebar.success("🧠 Agente Letta carregado com memória persistente!")
        else:
            # Cria um novo agente
            novo_agente = client.agents.create(
                name=AGENT_NAME,
                model="groq/llama-3.3-70b-versatile",
                embedding="openai/text-embedding-3-small",
                memory_blocks=[
                    {"label": "persona", "value": "Você é um assistente especialista em programação, chamado Agente Coder. Você é direto, útil e responde em português."},
                    {"label": "human", "value": f"O usuário é {user_email}. Ainda não tenho informações sobre ele."}
                ]
            )
            agent_id = novo_agente.id
            st.sidebar.success("🧠 Novo agente Letta criado com memória persistente!")
        LETTA_ACTIVE = True
    except Exception as e:
        st.sidebar.warning(f"⚠️ Erro ao conectar com Letta: {e}. Usando modo fallback.")
        LETTA_ACTIVE = False
else:
    LETTA_ACTIVE = False
    if not LETTA_AVAILABLE:
        st.sidebar.info("ℹ️ Letta não instalado. Usando memória local.")
    else:
        st.sidebar.info("ℹ️ LETTA_API_KEY não configurada. Usando memória local.")

init_db()

# --- VALIDAR GROQ API KEY ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("❌ GROQ_API_KEY não configurada nos Secrets do Streamlit.")
    st.stop()

# --- MODELO PRINCIPAL ---
modelo_principal = "openai/gpt-oss-120b"

# --- GERENCIAMENTO DE SESSÃO ---
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None

# --- SIDEBAR ---
with st.sidebar:
    st.title("📋 Conversas")
    if st.button("➕ Nova Conversa", use_container_width=True):
        novo_id = criar_nova_conversa(user_email)
        st.session_state.active_chat_id = novo_id
        st.rerun()
    
    st.markdown("---")
    conversas = listar_conversas(user_email)
    if not conversas:
        st.info("Nenhuma conversa encontrada.")
    else:
        for chat_id, titulo in conversas:
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                if st.button(f"{titulo}", key=f"chat_{chat_id}", use_container_width=True):
                    st.session_state.active_chat_id = chat_id
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{chat_id}"):
                    deletar_conversa(chat_id)
                    st.rerun()
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🧠 Memórias")
    
    # Mostrar memórias do Letta se ativo
    if LETTA_ACTIVE:
        try:
            agent = client.agents.retrieve(agent_id)
            for block in agent.memory_blocks:
                if block.label == "human":
                    st.sidebar.info(f"👤 {block.value[:200]}...")
                elif block.label == "persona":
                    st.sidebar.info(f"🤖 {block.value[:200]}...")
        except:
            pass
    else:
        # Mostrar memórias locais
        conn = sqlite3.connect("memoria_agente.db")
        c = conn.cursor()
        c.execute("SELECT fato FROM memorias WHERE user_email = ? ORDER BY criado_em DESC LIMIT 10", (user_email,))
        memorias = c.fetchall()
        conn.close()
        if memorias:
            for mem in memorias:
                st.sidebar.write(f"- {mem[0]}")
        else:
            st.sidebar.info("Nenhuma memória salva ainda.")
    
    st.sidebar.markdown("---")
    st.sidebar.write(f"🔑 Conectado como: {user_email}")
    if st.sidebar.button("🚪 Sair"):
        st.logout()

# --- ÁREA PRINCIPAL ---
if not st.session_state.active_chat_id:
    st.session_state.active_chat_id = criar_nova_conversa(user_email)

st.title("🤖 Agente Coder")

messages = carregar_historico_chat(st.session_state.active_chat_id)
for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

chat_prompt = st.chat_input("Digite sua mensagem...")

if chat_prompt:
    # Salvar mensagem do usuário no histórico local
    salvar_mensagem(st.session_state.active_chat_id, user_email, "user", chat_prompt)
    atualizar_titulo_conversa(st.session_state.active_chat_id, chat_prompt)
    
    with st.chat_message("user"):
        st.markdown(chat_prompt)
    
    # --- GERAR RESPOSTA ---
    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                # Se Letta estiver ativo, usar ele
                if LETTA_ACTIVE:
                    response = client.agents.messages.create(
                        agent_id=agent_id,
                        messages=[{"role": "user", "content": chat_prompt}]
                    )
                    bot_reply = ""
                    for msg in response.messages:
                        if hasattr(msg, "message_type") and msg.message_type == "assistant_message":
                            bot_reply += getattr(msg, "content", "")
                    st.markdown(bot_reply)
                    
                    # Salvar no histórico local também
                    salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
                    
                    # Mostrar memórias atualizadas
                    with st.expander("🧠 Memórias atualizadas"):
                        agent = client.agents.retrieve(agent_id)
                        for block in agent.memory_blocks:
                            if block.label == "human":
                                st.write(f"**👤 Sobre você:** {block.value}")
                            elif block.label == "persona":
                                st.write(f"**🤖 Sobre o agente:** {block.value}")
                
                # Fallback: usar Groq diretamente
                else:
                    client_groq = Groq(api_key=str(api_key).strip())
                    
                    # Buscar memórias locais
                    memorias = buscar_memorias_local(user_email, chat_prompt, limit=3)
                    texto_memorias = "\n".join([f"- {mem}" for mem in memorias]) if memorias else "Nenhuma memória relevante encontrada."
                    
                    system_prompt = f"""Você é um assistente especialista em programação, baseado no modelo da Groq.
                    
                    MEMÓRIAS SOBRE O USUÁRIO:
                    {texto_memorias}
                    
                    Use essas memórias para personalizar suas respostas. Seja natural e direto."""
                    
                    historico = carregar_historico_chat(st.session_state.active_chat_id)
                    messages_api = [{"role": "system", "content": system_prompt}] + historico
                    
                    chat_completion = client_groq.chat.completions.create(
                        model=modelo_principal,
                        messages=messages_api
                    )
                    bot_reply = chat_completion.choices[0].message.content
                    st.markdown(bot_reply)
                    
                    # Salvar resposta no histórico
                    salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
                    
                    # Tentar extrair memórias localmente (simples)
                    if "meu nome é" in chat_prompt.lower():
                        match = re.search(r"meu nome é\s+([A-Za-zÀ-ÖØ-öø-ÿ\s]+)", chat_prompt, re.IGNORECASE)
                        if match:
                            nome = match.group(1).strip()
                            salvar_memoria_local(user_email, f"nome: {nome}")
                            st.toast(f"🧠 Memória salva: nome -> {nome}", icon="✅")
                
            except Exception as err:
                st.error(f"⚠️ Erro: {err}")

st.caption("🧠 Este agente pode ter memória persistente via Letta.")
