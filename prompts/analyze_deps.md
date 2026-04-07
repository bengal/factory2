You are analyzing user story specifications to identify dependencies between them.

For each story, determine which other stories must be implemented BEFORE it. A story depends on another if:

- It references types, modules, or functionality that the other story creates
- It extends or modifies behavior introduced by the other story
- It cannot compile or function without the other story's code in place

Be conservative: only declare a dependency if implementation ORDER matters. Two stories that touch different parts of the codebase are independent even if they're in the same domain.

## Output

Write TWO files:

1. The human-readable analysis (path given below) — for each dependency you identify, explain WHY story A depends on story B.

2. The machine-readable JSON (path given below) — use this EXACT format:

```json
{
  "stories": ["story-id-1", "story-id-2"],
  "dependencies": {
    "story-id-1": [],
    "story-id-2": ["story-id-1"]
  }
}
```

Rules:
- Story IDs are the spec filenames without the `.md` extension
- If a story has no dependencies, its array must be empty `[]`
- Every story must appear in both `stories` array and `dependencies` object
- If you detect a circular dependency, document it in the analysis and break the cycle by removing the weakest edge
