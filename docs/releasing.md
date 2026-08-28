# Releasing

Publishing is manual on purpose. A version that reaches PyPI can never be reused,
so it should not happen as a side effect of merging something.

## One-time setup (a human has to do this)

open-primeagent publishes with **Trusted Publishing**, so there is no API token
to store in the repository, leak, or rotate. PyPI verifies the GitHub workflow's
identity directly.

1. Sign in to <https://pypi.org> (and <https://test.pypi.org> for rehearsals).
2. Go to *Your projects → Publishing*, or, before the first release,
   *Account settings → Publishing → Add a pending publisher*.
3. Register a pending publisher with exactly:

   | field | value |
   |---|---|
   | PyPI project name | `open-primeagent` |
   | Owner | `softkleenex` |
   | Repository name | `open-primeagent` |
   | Workflow name | `release.yml` |
   | Environment name | `release` |

4. In the GitHub repository, create an environment called `release`
   (*Settings → Environments*). Add reviewers to it if you want a second pair of
   eyes before anything goes out.

The name `open-primeagent` was unclaimed on both indexes when this was written.

## Rehearse on TestPyPI first

*Actions → release → Run workflow*, with `repository: testpypi`. Then check the
artifact actually installs from the index, not just from a local file:

```bash
uv venv /tmp/rehearsal
uv pip install --python /tmp/rehearsal/bin/python \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  open-primeagent
/tmp/rehearsal/bin/python -c "import opa, opa_runtime; print(opa.__version__)"
```

The extra index is needed because the dependencies live on real PyPI.

## Release

1. Bump `version` in `pyproject.toml` and in `runtime/pyproject.toml`. They must
   match; `opa.__version__` reads the installed metadata, so nothing else needs
   touching.
2. Commit, then tag:

   ```bash
   git tag -a v0.1.0 -m "0.1.0"
   git push origin v0.1.0
   ```

The tag runs the workflow, which refuses to publish unless ruff and the whole
suite pass, the metadata renders, and the built wheel imports in a clean
environment.

## Then verify the promise in the README

```bash
claude mcp add opa -- uvx open-primeagent
claude mcp list        # opa: ✔ Connected
```

That line is the first thing anyone reads. It has been wrong once already —
`opa-runtime` used to be an unpublishable workspace member — so check it against
the real index rather than assuming.
