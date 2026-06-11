import psycopg2

def test_fts():
    conn = psycopg2.connect(dbname='project_name_docs', user='postgres', password='password', host='localhost')
    cur = conn.cursor()
    
    # Original user question
    question = "what roles have converter attribute and can u say what is converter?"
    
    # Simple stop words filter (we can refine this)
    stop_words = {"what", "wat", "is", "are", "the", "a", "an", "explain", "describe", "define", "under", "for", "list", "all", "and", "give", "its", "name", "-", "can", "u", "have", "say"}
    
    q_lower = question.lower().replace("?", "").replace("'", "")
    keywords = [w for w in q_lower.split() if w not in stop_words and len(w) > 1]
    
    # Keywords: ['roles', 'converter', 'attribute', 'converter']
    # Join with OR for websearch_to_tsquery
    search_query = " OR ".join(set(keywords))
    print("FTS Query:", search_query)
    
    sql = """
        SELECT role_name, attribute_name, class_name, description,
               ts_rank(
                   to_tsvector('english', 
                       coalesce(role_name, '') || ' ' || 
                       coalesce(attribute_name, '') || ' ' || 
                       coalesce(class_name, '') || ' ' || 
                       coalesce(group_name, '') || ' ' || 
                       coalesce(description, '')
                   ),
                   websearch_to_tsquery('english', %s)
               ) as rank
        FROM role_mappings
        WHERE to_tsvector('english', 
                   coalesce(role_name, '') || ' ' || 
                   coalesce(attribute_name, '') || ' ' || 
                   coalesce(class_name, '') || ' ' || 
                   coalesce(group_name, '') || ' ' || 
                   coalesce(description, '')
              ) @@ websearch_to_tsquery('english', %s)
        ORDER BY rank DESC
        LIMIT 10;
    """
    
    cur.execute(sql, (search_query, search_query))
    rows = cur.fetchall()
    print(f"Found {len(rows)} matches.")
    for r in rows:
        print(r[:3], r[-1])

if __name__ == '__main__':
    test_fts()
