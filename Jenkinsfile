pipeline {
    agent { label 'docker-agent'}

    environment {
        PYTHON_VERSION = '3.13'
        PATH = "${WORKSPACE}/.venv/bin:${env.PATH}"
        COMPOSE_PROJECT_NAME = 'sentinelops'
    }

    stages {
        stage('Config & Static Validation') {
            steps {
                sh 'python3 -m venv .venv'
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
            environment {
                POSTGRES_HOST = 'postgres'
            }
            steps {
                sh 'cp .env.test .env'
                sh 'docker compose up -d postgres'
                sh './automation/scripts/init_test_db.sh'
                sh 'ruff check .'
                sh 'ruff format --check .'
                sh 'pytest --cov=automation --cov-report=xml -m "not e2e"'
            }
        }
        stage('Quality Gate') {
            tools {
                'hudson.plugins.sonar.SonarRunnerInstallation' 'SonarScanner'
            }
            steps {
                withSonarQubeEnv('SonarCloud') {
                    sh 'sonar-scanner'
                }
                timeout(time: 5, unit: 'MINUTES') {
                    waitForQualityGate abortPipeline: true
                }
            }
        }
        stage('Container Build') {
            steps {
                sh 'docker build -t sentinelops/api:jenkins-${BUILD_NUMBER} docker/api'
                sh 'docker build -f docker/webhook-handler/Dockerfile -t sentinelops/webhook-handler:jenkins-${BUILD_NUMBER} .'
                sh 'docker build -f docker/worker/Dockerfile -t sentinelops/worker:jenkins-${BUILD_NUMBER} .'
                sh 'docker build -f docker/report-generator/Dockerfile -t sentinelops/report-generator:jenkins-${BUILD_NUMBER} .'
            }
        }
        stage('Vulnerability Scan') {
            steps {
                sh '''
                    for image in api webhook-handler worker report-generator; do
                        docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \\
                            aquasec/trivy:latest image --exit-code 1 --severity HIGH,CRITICAL \\
                            sentinelops/$image:jenkins-${BUILD_NUMBER}
                    done
                '''
            }
        }
    }

    post {
        always {
            sh 'docker compose rm -sf postgres || true'
        }
    }
}
