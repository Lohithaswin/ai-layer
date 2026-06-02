"""Quick test script to validate NLP improvements for acronym/definition questions."""

import requests
import json
from datetime import datetime

API_BASE = "http://localhost:8000"

# Test questions focusing on acronyms and definitions
TEST_QUESTIONS = [
    "What is PROJECT_NAME?",
    "What is PROJECT_NAME full form?",
    "What does PROJECT_NAME stand for?",
    "What is JWT?",
    "What does API mean?",
    "What is ChromaDB?",
]

def test_question(question):
    """Test a single question and evaluate response quality."""
    print(f"\n{'='*70}")
    print(f"QUESTION: {question}")
    print(f"TIME: {datetime.now().strftime('%H:%M:%S')}")
    print('='*70)
    
    try:
        response = requests.post(
            f"{API_BASE}/chat",
            json={"question": question},
            timeout=60
        )
        
        if response.status_code != 200:
            print(f"❌ ERROR: API returned {response.status_code}")
            return False
        
        data = response.json()
        
        # Extract answer (remove footer)
        answer = data.get("answer", "")
        footer_idx = answer.find("\n\n---\n**Sources:**")
        if footer_idx > -1:
            answer = answer[:footer_idx]
        
        print(f"\n📝 ANSWER:\n{answer}\n")
        
        # Evaluate quality
        print("\n📊 QUALITY METRICS:")
        
        # Check 1: Does it start with clear definition?
        starts_clear = any(phrase in answer.lower() for phrase in [
            "stands for", "means", "is an", "acronym for", "full form"
        ])
        print(f"  ✓ Clear definition at start: {'YES' if starts_clear else 'NO'}")
        
        # Check 2: Does it have "not mentioned" contradiction?
        has_contradiction = "not explicitly mentioned" in answer.lower() and "[" in answer
        print(f"  ✓ No contradictions: {'YES' if not has_contradiction else 'NO'}")
        
        # Check 3: Has citations?
        has_citations = "[" in answer and "]" in answer
        print(f"  ✓ Has citations: {'YES' if has_citations else 'NO'}")
        
        # Check 4: Has structure (headers)?
        has_structure = "##" in answer
        print(f"  ✓ Structured (headers): {'YES' if has_structure else 'NO'}")
        
        # Show metrics
        print(f"\n📈 RESPONSE METADATA:")
        print(f"  Processing time: {data.get('processing_time_ms', 0):.0f}ms")
        print(f"  Retrieval time: {data.get('retrieval_time_ms', 0):.0f}ms")
        print(f"  Sources retrieved: {data.get('num_sources_retrieved', 0)}")
        print(f"  Sources used: {data.get('num_sources_used', 0)}")
        print(f"  Question intent: {data.get('question_intent', 'unknown')}")
        print(f"  LLM used: {data.get('used_llm', False)}")
        
        # Show sources
        if data.get('sources'):
            print(f"\n📚 SOURCES ({len(data['sources'])}):")
            for src in data['sources']:
                print(f"  [{src['ref']}] {src['source_file']} (p.{src['page']}, {src['score']:.1%})")
                print(f"      {src['excerpt'][:100]}...")
        
        # Overall quality score
        quality_score = sum([
            starts_clear,
            not has_contradiction,
            has_citations,
            has_structure
        ]) / 4 * 100
        
        print(f"\n🎯 OVERALL QUALITY: {quality_score:.0f}%")
        if quality_score >= 75:
            print("✅ GOOD ANSWER")
        elif quality_score >= 50:
            print("⚠️  ACCEPTABLE ANSWER")
        else:
            print("❌ POOR ANSWER")
        
        return quality_score >= 75
        
    except requests.exceptions.ConnectionError:
        print("❌ ERROR: Cannot connect to API")
        print("   Make sure FastAPI is running: uvicorn api:app --reload --port 8000")
        return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("NLP IMPROVEMENTS TEST SUITE")
    print("Testing acronym/definition question handling")
    print("="*70)
    
    results = {}
    for question in TEST_QUESTIONS:
        try:
            results[question] = test_question(question)
        except Exception as e:
            print(f"Test failed: {e}")
            results[question] = False
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\n✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")
    print(f"📊 Success Rate: {passed/total*100:.0f}%")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! NLP improvements are working well.")
    elif passed >= total * 0.75:
        print("\n👍 MOST TESTS PASSED. Good improvement!")
    else:
        print("\n⚠️  SOME TESTS FAILED. May need further tuning.")
    
    # Show which questions performed well
    print("\n📋 RESULTS BY QUESTION:")
    for question, passed in results.items():
        status = "✅" if passed else "❌"
        print(f"  {status} {question}")


if __name__ == "__main__":
    main()
