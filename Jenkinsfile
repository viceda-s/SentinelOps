pipeline {
    agent { label 'docker-agent'}

    environment {
        PYTHON_VERSION = '3.13'
    }

    stages {
        stage('Config & Static Validation') {
            steps {
                sh 'pip install -r requirements-dev.txt'
                sh 'shellcheck automation/scripts/*.sh docker/postgres/init/007_create_roles.sh'
                sh 'yamllint docker cmdb .github/workflows docker-compose.yml'
                sh '''
                    for f in automation/scripts/*.sh; do
                        if [ ! -x "$f" ]; then
                            echo "$f is not executable"
                            exit 1
                        fi
                    done
                '''
                sh 'cp .env.example .env'
                sh './automation/scripts/bootstrap.sh --validate-only'
                sh '''
                    fail=0
                    for s in $(grep -oE '\\./[A-Za-z0-9_/.-]+\\.sh' README.md | sort -u); do
                        [ -f "$s" ] || { echo "readme references $s but it doesn't exist"; fail=1; }
                    done
                    exit $fail
                '''
            }
        }

        stage('Build & Test') {
            steps {
                sh 'cp .env.test .env'
                sh 'docker compose up -d postgres'
                sh './automation/scripts/init_test_db.sh'
                sh 'ruff check .'
                sh 'ruff format --check .'
                sh 'pytest --cov=automation --cov-report=xml -m "not e2e"'
            }
        }
    }

    post {
        always {
            sh 'docker compose down -v --remove-orphans || true'
        }
    }
}