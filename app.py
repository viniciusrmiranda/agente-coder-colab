import streamlit as st
import sqlite3
from groq import Groq
from duckduckgo_search import DDGS
import pypdf
import uuid
from mem0 import Memory

st.set_page_config(page_title="Agente Coder", page_icon="🤖", layout="wide")

# --- AUTENTICAÇÃO COM GOOGLE ---
if not st.user.is_logged_in:
    st.title("🤖 Agente Coder")
    st.write("Faça login com sua conta do Google para acessar a aplicação.")
    if st.button("🔑 Entrar com o Google"):
        st.login("google")
    st.stop()

user_email = st.user.email

# --- CONFIGURAÇÃO DO MEM0 (versão simplificada e validada) ---
# A documentação oficial sugere esta estrutura para a versão 2.x
config = {
    "llm": {
        "provider": "groq",
        "config": {
            "model": "llama3-70b-8192",
            "temperature": 0.1,
            "max_tokens": 2000,
        }
    },
    "embedder": {
        "provider": "sentence-transformers",
        "config": {
            "model": "all-MiniLM-L6-v2"
        }
    },
    "vector_store": {
        "provider": "none",  # desativa o banco vetorial para simplificar
    }
}

# Inicializa o Mem0
try:
    memory = Memory.from_config(config)
except Exception as e:
    st.error(f"Erro ao inicializar Mem0: {e}. Usando memória básica (sem busca semântica).")
    # Fallback: cria um objeto Memory com configuração padrão (que pode não funcionar com Groq)
    memory = Memory()

# --- BANCO DE DADOS (SQLite) ---
def init_db():
    conn = sqlite3.connect("memoria_agente.db")
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS conversas 
                 (chat_id TEXT PRIMARY KEY, user_email TEXT, titulo TEXT, 
                  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS historico 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, user_email TEXT, role TEXT, content TEXT)''')
    
    try:
        c.execute("SELECT user_email, chave, valor FROM perfil LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("DROP TABLE IF EXISTS perfil")
        c.execute("CREATE TABLE perfil (user_email TEXT, chave TEXT, valor TEXT, PRIMARY KEY (user_email, chave))")
    
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

init_db()

# --- VALIDAR GROQ API KEY ---
api_key = st.secrets.get("GROQ_API_KEY")
if not api_key:
    st.error("GROQ_API_KEY não configurada nos Secrets.")
    st.stop()

# --- MODELO ATIVO ---
active_model = "llama3-70b-8192"

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
    
    # --- EXIBIR MEMÓRIAS SALVAS (tentar com o Mem0) ---
    st.sidebar.subheader("🧠 Memórias")
    try:
        memorias = memory.search(query="", user_id=user_email, limit=10)
        if memorias and "results" in memorias and memorias["results"]:
            for mem in memorias["results"]:
                st.sidebar.write(f"- {mem['memory']}")
        else:
            st.sidebar.info("Nenhuma memória salva ainda.")
    except Exception as e:
        st.sidebar.info(f"Memórias indisponíveis: {str(e)[:50]}...")
    
    st.sidebar.markdown("---")
    st.sidebar.write(f"Conectado como: {user_email}")
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
    # 1. Salva a mensagem do usuário
    salvar_mensagem(st.session_state.active_chat_id, user_email, "user", chat_prompt)
    atualizar_titulo_conversa(st.session_state.active_chat_id, chat_prompt)
    
    with st.chat_message("user"):
        st.markdown(chat_prompt)
    
    # 2. Busca memórias relevantes no Mem0
    try:
        memorias_relevantes = memory.search(
            query=chat_prompt,
            user_id=user_email,
            limit=3
        )
        texto_memorias = ""
        if memorias_relevantes and "results" in memorias_relevantes:
            for mem in memorias_relevantes["results"]:
                texto_memorias += f"- {mem['memory']}\n"
    except Exception as e:
        texto_memorias = "[Erro ao buscar memórias]"
    
    # 3. Gera a resposta do assistente
    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                client = Groq(api_key=str(api_key).strip())
                
                system_prompt = f"""Você é um assistente especialista em programação, baseado no modelo {active_model} da Groq.
                
                MEMÓRIAS SOBRE O USUÁRIO:
                {texto_memorias if texto_memorias else "Nenhuma memória registrada ainda."}
                
                Use essas memórias para personalizar suas respostas."""
                
                historico = carregar_historico_chat(st.session_state.active_chat_id)
                messages_api = [{"role": "system", "content": system_prompt}] + historico
                
                chat_completion = client.chat.completions.create(
                    model=active_model,
                    messages=messages_api
                )
                bot_reply = chat_completion.choices[0].message.content
                st.markdown(bot_reply)
                
                # 4. Salva a resposta
                salvar_mensagem(st.session_state.active_chat_id, user_email, "assistant", bot_reply)
                
                # 5. Salva a interação na memória do Mem0
                try:
                    memory.add(
                        [
                            {"role": "user", "content": chat_prompt},
                            {"role": "assistant", "content": bot_reply}
                        ],
                        user_id=user_email
                    )
                except Exception as e:
                    st.warning(f"⚠️ Erro ao salvar memória: {e}")
                
            except Exception as err:
                st.error(f"⚠️ Erro: {err}")
