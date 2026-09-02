# Audit and Cleanup of the Inherited `.github` Folder

## Finding

The original folder was copied from an unrelated Laravel medical platform named SaludPlus. It included:

- Laravel/Blade/PHP conventions.
- Alpine.js, Material Icons, Metronic and historical Bootstrap rules.
- Medical records, allergies, diagnoses, pharmacy, hospitals, patient profiles, and Venezuelan medical-security plans.
- Pest PHP test conventions.
- A misspelled directory: `.github/instrucctions`.
- Contradictory design generations: the `.bak` file requires Metronic while newer files prohibit it.

None of those domain or stack instructions apply to Venuz.

## Reusable ideas retained

- Plan before implementation.
- Define objective, data model, routes, files, UI, tests, and risks.
- Maintain consistent component patterns.
- Treat security and auditability as first-class requirements.
- Keep documentation synchronized with implementation.

## New center of operations

- `AGENTS.md`: instructions for Codex and repository agents.
- `.github/copilot-instructions.md`: global GitHub Copilot context.
- `.github/instructions/*.instructions.md`: scoped frontend, backend, database, trading, testing, and documentation rules.
- `.github/prompts/*.prompt.md`: master and phase prompts.
- `docs/*`: authoritative product, architecture, strategy, security, and delivery documents.

## Cleanup result

With the user's authorization, the old `.github/instrucctions/**` and medical `.github/plans/**` directories were removed from the repository before the initial commit. A temporary recoverable backup was created during cleanup and is not part of the repository. The active `.github` folder now contains only Venuz instructions, prompts, and contribution templates.
