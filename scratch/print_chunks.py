from src.vector_store import get_vector_store
store = get_vector_store()

def dump_page(title, path, page_num):
    chunks = store.get_chunks_for_page(path, page_num)
    print(f"=== {title} (Page {page_num}) ===")
    if not chunks:
        print("NO CHUNKS")
        return
    for c in chunks:
        idx = c.get('chunk_index')
        text = c.get('parent_text') or c.get('text', '')
        print(f"--- Chunk {idx} (len={len(text)}) ---")
        print(text)

dump_page("MFA User Doc Page 7", 'Release-Documents/PROJECT_MODULE Documents/MFA/MFA_User_Document.pdf', 7)
dump_page("MFA User Doc Page 8", 'Release-Documents/PROJECT_MODULE Documents/MFA/MFA_User_Document.pdf', 8)
dump_page("MFA User Doc Page 9", 'Release-Documents/PROJECT_MODULE Documents/MFA/MFA_User_Document.pdf', 9)
