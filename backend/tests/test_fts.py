import urllib.request
import urllib.parse
import json

def test_fts():
    base_url = "http://127.0.0.1:8000/api/v1/jobs"

    # 1. Stemmed search: "engineers" should match "Engineer"
    q_stem = urllib.parse.urlencode({"q": "engineers"})
    req1 = urllib.request.Request(f"{base_url}?{q_stem}")
    with urllib.request.urlopen(req1) as resp:
        res1 = json.loads(resp.read().decode())
        print(f"[1/4] Stemmed search for 'engineers': found {res1['total']} matches.")
        assert res1["total"] > 0
        item = res1["items"][0]
        print(f"      Matched title: '{item['title']}', relevance: {item.get('relevance_score')}")

    # 2. Phrase search: '"Machine Learning"'
    q_phrase = urllib.parse.urlencode({"q": '"Machine Learning"'})
    req2 = urllib.request.Request(f"{base_url}?{q_phrase}")
    with urllib.request.urlopen(req2) as resp:
        res2 = json.loads(resp.read().decode())
        print(f"[2/4] Phrase search for '\"Machine Learning\"': found {res2['total']} matches.")
        assert res2["total"] > 0
        print(f"      Snippet preview: {res2['items'][0].get('snippet')}")

    # 3. Sort by salary
    q_salary = urllib.parse.urlencode({"sort_by": "salary"})
    req3 = urllib.request.Request(f"{base_url}?{q_salary}")
    with urllib.request.urlopen(req3) as resp:
        res3 = json.loads(resp.read().decode())
        print(f"[3/4] Sort by salary returned {len(res3['items'])} items.")

    # 4. Multi-filter search: q=python & is_remote=true & min_salary=100000
    q_multi = urllib.parse.urlencode({"q": "python", "is_remote": "true", "min_salary": "100000"})
    req4 = urllib.request.Request(f"{base_url}?{q_multi}")
    with urllib.request.urlopen(req4) as resp:
        res4 = json.loads(resp.read().decode())
        print(f"[4/4] Multi-filter search (q=python, remote=true, min_salary=100k) found {res4['total']} matches.")
        assert res4["total"] > 0

    print("=== ALL FTS SEARCH TESTS PASSED ===")

if __name__ == "__main__":
    test_fts()
