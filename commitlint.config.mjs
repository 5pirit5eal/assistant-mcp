/**
 * Commitlint rules mirroring the Conventional Commits types configured in
 * .releaserc (semantic-release derives the version from these).
 */
const commitlintConfig = {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      [
        "feat",
        "feature",
        "fix",
        "perf",
        "revert",
        "docs",
        "style",
        "chore",
        "refactor",
        "test",
        "build",
        "ci",
      ],
    ],
  },
};

export default commitlintConfig;
