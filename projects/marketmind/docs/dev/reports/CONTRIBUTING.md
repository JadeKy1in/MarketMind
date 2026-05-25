# Contributing to SkillFoundry

Thank you for your interest in SkillFoundry! This project follows the **Skill Foundry Standard** — a constitutional process for developing, qualifying, and registering infrastructure skills.

## Development Process

1. **Review the architecture**: Read `systemPatterns.md` and `techContext.md` before making changes.
2. **Follow the SPARC loop**: Specification → Pseudocode → Architecture → Refinement → Completion.
3. **No external dependencies**: This project enforces zero npm indirect dependencies. Use Node 18+ built-ins.
4. **Test before commit**: Run the full test suite before pushing — 100% pass rate is required.

## Code Standards

- **TypeScript strict mode**: Always enabled.
- **Single-Navigation Architecture**: For browser automation, navigate ONCE at entry point.
- **Safe Timeout Pattern**: Use `new Promise<T>` with `clearTimeout` in both resolve and reject handlers.
- **Zero External Dependencies**: No third-party npm packages for core functionality.

## Pull Request Process

1. Ensure all tests pass: `cd infrastructure/skills/browser-automation && npx jest`
2. Run TypeScript check: `npx tsc --noEmit`
3. Update the SKILLS_MANIFEST.json if adding or modifying a skill.
4. Update infrastructure/README.md with any new capabilities.
5. Submit the PR with a clear description of changes.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.