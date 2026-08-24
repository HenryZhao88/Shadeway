/* There was no ESLint config in the repo, so `npm run lint` — and therefore the
 * web half of `make lint` — had never actually run. This is the smallest config
 * that lints what the client is written in.
 *
 * Deliberately not type-aware: a type-aware pass needs a second full TypeScript
 * program, and `tsc -b` already runs in `make test` on the same sources, so it
 * would be paying twice for the same answer.
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  plugins: ['@typescript-eslint'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
  ],
  ignorePatterns: ['dist', 'node_modules', 'src/api/types.ts'],
  rules: {
    // deck.gl and MapLibre hand back plenty of loosely typed objects; the code
    // narrows them at the point of use, which is the right place.
    '@typescript-eslint/no-explicit-any': 'warn',
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
  },
  overrides: [
    {
      files: ['**/__tests__/**'],
      env: { node: true },
    },
  ],
};
