### Lecture Kaki 
  - FE - React + Radix UI + React Router + Vite
  - BE - FastAPI

### Contributing

- Work on a feature branch and open a pull request into `main`.
- Keep commits focused and use Conventional Commits, for example
  `chore: establish repository workflow guardrails`.
- Run the relevant local checks before committing. Include their results in the
  PR and obtain one teammate's approval before merging.
- Do not force-push shared branches; add a follow-up commit instead.

Enable the repository's Git hooks once per checkout (Git for Windows supported):

```sh
git config --local core.hooksPath .githooks
```

The hooks block commits on `main` and pushes targeting `main`. Local hooks are
bypassable; the repository owner must configure GitHub branch protection to
enforce pull requests and one approving review. Required CI checks will be added
once the initial workflow exists.
