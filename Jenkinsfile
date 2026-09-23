pipeline {
    agent { label 'docker-agent'}

    parameters {
        booleanParam(name: 'RUN_E2E_CHAOS', defaultValue: false, description: 'Run the E2E chaos test suite (slow, tears down and rebuilds the full stack)')
    }

    environment {
        PYTHON_VERSION = '3.13'
        PATH = "${WORKSPACE}/.venv/bin:${env.PATH}"
    }

    stages {
        stage('Config & Static Validation') {
            steps {
                sh 'python3 -m venv .venv'
                sh 'pip install -r requirements-dev.txt'
                sh 'shellcheck automation/scripts/*.sh docker/postgres/init/007_create_roles.sh'
                sh 'yamllint docker cmdb .github/workflows docker-compose.yml docker-compose.ci.yml'
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
                POSTGRES_HOST = '127.0.0.1'
                POSTGRES_PORT = '55432'
            }
            steps {
                sh 'cp .env.test .env'
                sh 'docker compose -f docker-compose.ci.yml -p sentinelops-ci up -d --wait postgres'
                sh './automation/scripts/init_test_db.sh'
                sh 'ruff check .'
                sh 'ruff format --check .'
                sh 'pytest --cov=automation --cov-report=xml -m "not e2e"'
            }
            post {
                always {
                    sh 'docker compose -f docker-compose.ci.yml -p sentinelops-ci down -v || true'
                }
            }
        }
        stage('Quality Gate') {
            steps {
                script {
                    def scannerHome = tool 'SonarScanner'
                    withSonarQubeEnv('SonarCloud') {
                        sh "${scannerHome}/bin/sonar-scanner"
                    }
                }
                timeout(time: 5, unit: 'MINUTES') {
                    waitForQualityGate abortPipeline: true
                }
            }
        }
        stage('Release Please') {
            when { branch 'main' }
            steps {
                catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                    withCredentials([usernamePassword(credentialsId: 'github-pat', usernameVariable: 'GITHUB_USER', passwordVariable: 'GITHUB_TOKEN')]) {
                        sh '''
                            release-please release-pr \\
                                --repo-url=viceda-s/SentinelOps \\
                                --token="$GITHUB_TOKEN"
                            release-please github-release \\
                                --repo-url=viceda-s/SentinelOps \\
                                --token="$GITHUB_TOKEN"
                        '''
                    }
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
                            -v "$WORKSPACE/.trivyignore:/.trivyignore" \\
                            -v trivy-cache:/root/.cache/trivy \\
                            aquasec/trivy:latest image --exit-code 1 --severity HIGH,CRITICAL \\
                            --ignorefile /.trivyignore \\
                            sentinelops/$image:jenkins-${BUILD_NUMBER}
                    done
                '''
            }
        }
        stage('E2E Chaos') {
            when {
                expression { return params.RUN_E2E_CHAOS }
            }
            steps {
                sh 'cp .env.test .env'
                sh './automation/scripts/bootstrap.sh'
                sh 'pytest -m e2e'
            }
            post {
                failure {
                    sh 'docker compose logs --no-color > compose-logs.txt || true'
                    archiveArtifacts artifacts: 'compose-logs.txt, diagnostics/**, .chaos/**', allowEmptyArchive: true
                }
                always {
                    sh '''
                        APP_SERVICES=$(docker compose config --services | grep -vE '^jenkins(-agent)?$')
                        docker compose rm -sf $APP_SERVICES || true
                    '''
                }
            }
        }
        stage('Archive & Report') {
            steps {
                archiveArtifacts artifacts: 'coverage.xml', allowEmptyArchive: true
                echo "SonarQube Cloud report: check the Quality Gate stage output above for the dashboard link."
                echo "Trivy scan results: check the Vulnerability Scan stage console output above."
            }
        }
    }

    post {
        always {
            sh 'docker compose rm -sf postgres || true'
        }
    }
}
