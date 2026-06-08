from src.vector_store import get_vector_store
store = get_vector_store()

print("--- MFA Server ---")
for pg in range(23, 28):
    chunks = store.get_chunks_for_page('Release-Documents/PROJECT_MODULE Documents/MFA/MFA Server - Installation and Configuration.pdf', pg)
    if chunks:
        for c in chunks[:1]:
            txt = (c.get('parent_text') or c.get('text',''))[:150]
            idx = c.get('chunk_index')
            length = len(c.get('parent_text') or c.get('text',''))
            print(f'Page {pg}: chunk_idx={idx}, len={length}')
            print(f'Text: {repr(txt)}')
    else:
        print(f'Page {pg}: NO CHUNKS')

print("\n--- MFA User Document ---")
for pg in range(2, 10):
    chunks = store.get_chunks_for_page('Release-Documents/PROJECT_MODULE Documents/MFA/MFA_User_Document.pdf', pg)
    if chunks:
        for c in chunks[:1]:
            txt = (c.get('parent_text') or c.get('text',''))[:150]
            idx = c.get('chunk_index')
            length = len(c.get('parent_text') or c.get('text',''))
            print(f'UserDoc Page {pg}: chunk_idx={idx}, len={length}')
            print(f'Text: {repr(txt)}')
    else:
        print(f'UserDoc Page {pg}: NO CHUNKS')
