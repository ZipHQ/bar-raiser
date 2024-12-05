# bar-raiser

Bar-Raiser is a cutting-edge framework designed to help engineering teams tackle technical debt, streamline development workflows, and elevate code quality.

### Main Features

Create GitHub Checks for Enhanced Developer Experiences:

- **Simplified Results**: View linter or test results in a dedicated check page, eliminating the need to sift through console output.
- **Inline Annotations**: View linter or test errors as annotations on GitHub Pull Requests, making it easier to understand errors in the context of the code.
- **Autofix Support**: Apply auto-fixes with a single click. This feature requires setting up a web service to receive GitHub webhook events and apply the autofix on the PR.
- **Slack Notifications**: Sends Slack notifications on check failures based on a provided mapping from GitHub login to Slack user ID. A SLACK_BOT_TOKEN and a Github login to Slack user ID mapping file is needed.

The `checks/annotate_ruff.py` module provides the following main features:

- **Ruff Integration**: Runs Ruff formatter and linter, parses the output, and creates GitHub check runs with annotations and actions.
- **Autofix Support**: Provides an autofix action to automatically fix issues detected by Ruff.

The `checks/annotate_pytest.py` module provides the following main features:

- **Pytest Integration**: Parses Pytest JSON reports and creates GitHub check runs with annotations for failed tests.

## Getting Started (For Developers)

1. Clone the repository:
   ```sh
   git clone https://github.com/ZipHQ/bar-raiser.git
   ```
2. Install PDM:
   ```sh
   pip install pdm
   ```
3. Install dependencies in a local .venv folder:
   ```sh
   pdm install
   ```
4. Install pre-commit hooks:
   ```sh
   pdm run pre-commit install
   ```

### Dependencies

The project uses the following dependencies:

- [PyGithub](https://github.com/PyGithub/PyGithub) (MIT License): A Python library to access the GitHub API v3.
- [GitPython](https://github.com/gitpython-developers/GitPython) (BSD License): A Python library used to interact with Git repositories.
- [cryptography](https://github.com/pyca/cryptography) (Apache License 2.0 or BSD License): A Python library providing cryptographic recipes and primitives.
- [slackclient](https://github.com/slackapi/python-slack-sdk) (MIT License): A Python library for interacting with the Slack API.

### Development Dependencies

The project also includes development dependencies for testing, linting, and code quality:

- [pytest](https://github.com/pytest-dev/pytest) (MIT License): A framework that makes building simple and scalable test cases easy.
- [diff-cover](https://github.com/Bachmann1234/diff-cover) (MIT License): A tool for checking which lines of code are covered by tests.
- [pytest-cov](https://github.com/pytest-dev/pytest-cov) (MIT License): A plugin for measuring code coverage with pytest.
- [ruff](https://github.com/charliermarsh/ruff) (MIT License): An extremely fast Python linter and formatter.
- [pyright](https://github.com/microsoft/pyright) (MIT License): A static type checker for Python.
- [pre-commit](https://github.com/pre-commit/pre-commit) (MIT License): A framework for managing and maintaining multi-language pre-commit hooks.
- [pytest-json-report](https://github.com/numirias/pytest-json-report) (MIT License): A plugin for creating JSON reports with pytest.

### Pre-commit Hooks

Pre-commit hooks are used to run checks automatically when you commit code. These checks help ensure code quality and consistency. The following hooks are configured:

- Trailing whitespace removal
- End-of-file fixer
- YAML file checks
- Large file checks
- PDM lock file check
- PDM sync
- Ruff for linting and formatting
- Pyright for type checking
- Pytest for running tests with coverage

To manually run the pre-commit hooks on all files, use:

```sh
pdm run pre-commit run --all-files
```

### Running Tests

To execute the test suite, run:

```sh
pdm run pytest
```

### Contributing

1. Fork the repository.
2. Create a new branch (`git checkout -b feature-branch`).
3. Make your changes.
4. Commit your changes (`git commit -m 'Add some feature'`).
5. Push to the branch (`git push origin feature-branch`).
6. Open a pull request.

### Coding Standards

- Follow the existing code style.
- Write unit tests for new features.
- Ensure all tests pass before submitting a pull request.

### Making a Release

To make a release, follow these steps:

1. Ensure all changes are committed and pushed to the main branch.
2. Create a new tag for the release:
   ```sh
   git tag -a vX.Y.Z -m "Release version X.Y.Z"
   git push origin vX.Y.Z
   ```
3. The [GitHub release workflow](https://github.com/ZipHQ/bar-raiser/actions/workflows/release.yml) will automatically build and publish the release based on the tagged commit.
