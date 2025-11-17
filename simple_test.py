from fastmatcher import ACMatcher

matcher = ACMatcher(["刘备", "关羽"], ignore_case=True, with_lineno=True)

text = "刘备三顾茅庐\n关羽温酒斩华雄"

for m in matcher.search(text):
    print(m.keyword, m.line_no, m.line_text)
