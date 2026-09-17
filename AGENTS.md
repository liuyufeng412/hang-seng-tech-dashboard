# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a blank scaffold. As the dashboard is implemented, keep application code in `src/`, reusable UI and utilities in clearly named subdirectories such as `src/components/` and `src/lib/`, static files in `public/`, and tests beside their source files or under `tests/`. Keep configuration files at the repository root. Avoid placing generated output or local secrets under version control.

## Build, Test, and Development Commands

No build tooling has been committed yet. When adding tooling, document its commands in `README.md` and keep these conventions consistent:

- `npm run dev` — start the local development server.
- `npm run build` — create a production build.
- `npm test` — run the automated test suite.
- `npm run lint` — check source formatting and static-analysis rules.

Do not add a command to this guide until it is defined in the project manifest or build configuration.

## Coding Style & Naming Conventions

Use the formatter and linter selected by the project; do not hand-format files against their output. Prefer two-space indentation for JavaScript/TypeScript, `PascalCase` for component files and exported components (for example, `MarketSummary.tsx`), and `camelCase` for functions, variables, and non-component modules. Use descriptive names that reflect financial concepts and avoid unexplained abbreviations.

## Testing Guidelines

Add focused tests with every behavior change, covering normal inputs and meaningful edge cases. Name tests after observable behavior, such as `market-summary.test.ts` or `MarketSummary.test.tsx`. Keep network-dependent data behind adapters or mocks so tests remain repeatable. Run the relevant test and lint commands before opening a pull request.

## Commit & Pull Request Guidelines

There is no established Git history yet. Use concise, imperative commit subjects, optionally following Conventional Commits: `feat: add sector performance chart` or `fix: handle missing quote data`. Keep commits scoped to one logical change. Pull requests should explain the user-visible result, note tests run, link related issues when available, and include screenshots or recordings for dashboard UI changes.

## Security & Configuration

Store API keys and tokens in local environment files such as `.env.local`; never commit them. Provide safe placeholder names in `.env.example` and document required variables without exposing values.
