// Формат коммитов — .claude/rules/git.md (Conventional Commits)
export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [2, 'always', ['feat', 'fix', 'docs', 'test', 'refactor', 'chore', 'ci', 'perf']],
    'subject-max-length': [2, 'always', 50],
    'subject-case': [0],
    'body-max-line-length': [2, 'always', 72],
  },
}
