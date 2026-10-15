# Budget-Aware Pathfinding Agent

계산 예산과 탐색 진행 상황에 따라 경로 탐색 전략을 **선택·유지·전환·반환**하는 규칙 기반 에이전트입니다. Python 3.11 이상과 표준 라이브러리만 사용합니다. 패키지 설치나 외부 서비스 연결이 필요하지 않습니다.

## 바로 실행

이 폴더에서 다음 명령을 실행합니다.

```powershell
python run.py demo
```

브라우저에 `http://127.0.0.1:8765`가 열립니다. Windows에서는 [launch_demo.cmd](launch_demo.cmd)를 더블클릭해도 됩니다. 서버 종료는 터미널에서 `Ctrl+C`입니다. 기본 포트가 사용 중이면 `--port 8766`을 추가하세요.

지도 크기·장애물 구조·난수 시드·지형 비용·확장 예산·탐색 방법을 바꿀 수 있습니다. 지도 클릭으로 장애물을 편집하고, 실행 후 탐색 기록을 재생하거나 특정 시점으로 이동할 수 있습니다. 판단 기록은 실제 제어 규칙과 관찰값에서 생성됩니다. 같은 지도에서 A*, Weighted A*, ARA*의 결과도 비교합니다.

```powershell
# 단일 실행과 지도·탐색 기록 저장
python run.py solve --structure u --size 50 --budget 1000 --weighted --seed 42 --output results/example.json

# 정확성·예산·중단/재개·평가 프로토콜 검증
python -m unittest discover -s tests -v

# 소규모 실험: 실제 allocation peak 계측 포함
python run.py experiment --config configs/smoke.json --output results/smoke

# 기획안의 원래 810개 지도–예산 조합(균일 비용 무작위 지도)
python run.py experiment --config configs/full.json --output results/full --rules results/study/tuning/frozen_rules.json

# 개발·검증 → 규칙 고정 → 확장 실험 → 시간 예산 보정·평가 → 보고서
python run.py study
```

전체 연구 실행은 `configs/extended.json`을 기본으로 사용합니다. 원래의 810개 조합에 가중 비용과 구조 지도 실험을 추가해 **720개 지도, 2,160개 지도–예산 조합, 15개 방법, 32,400회 평가 실행**으로 구성됩니다. 실행 시간은 컴퓨터 성능에 따라 달라집니다. 동일 출력 경로로 실행하면 그 경로의 실험 산출물을 새 결과로 덮어씁니다.

## 프로젝트 구성

```text
Budget-Aware Pathfinding Agent/
├── run.py                       직접 실행 진입점
├── launch_demo.cmd              Windows 시뮬레이터 실행
├── pyproject.toml               선택적 패키지 설치 설정
├── src/budget_pathfinding/
│   ├── grid.py                  4방향 격자·비용·지도 생성
│   ├── search.py                중단/재개 탐색기·ARA*
│   ├── controller.py            설명 가능한 규칙·임계값
│   ├── agent.py                 공통 예산·독립 상태·최선 경로 보존
│   ├── experiments.py           분할·시드·검증 선정·실험 실행
│   ├── analysis.py              짝지은 지표·신뢰구간·SVG·보고서
│   ├── server.py                로컬 HTTP API
│   ├── cli.py                   명령줄 도구
│   └── web/                     한국어 시뮬레이터 화면
├── configs/                     소규모·검증·전체·시간 실험 설정
├── data/maps/                   예시 지도
├── docs/                        원본 기획안·설계·평가 방법·진행 기록
├── scripts/                     실행·산출물 검증 도구
├── tests/                       unittest 기반 검증
└── results/
    ├── smoke/                   작은 실험·tracemalloc 계측
    └── study/
        ├── tuning/              개발·검증 결과·frozen_rules.json
        ├── evaluation/          최종 확장 예산 실험
        ├── time_calibration.json 독립 pilot의 시간 예산 보정
        └── time_evaluation/     실제 시간 제한 실험
```

## 비교 방법과 예산

고정 방법은 BFS, Dijkstra, A*, Greedy Best-First, Weighted A*(1.5, 3.0)입니다. 이외에 초기 선택만 수행하는 방법, 순환 균등 배분, 적응형, ARA*, 진행 정보 제거, 전환 금지, 조기 반환 제거, 전환 한도 제거, 첫 경로 즉시 반환을 제공합니다. `no_switch`와 `initial`은 동일한 동작의 제거 실험·기준선 이름입니다.

노드 확장 예산은 모든 탐색기가 공유합니다. 다른 전략이 같은 칸을 탐색하거나 한 탐색기가 칸을 재확장해도 예산에서 차감합니다. 전략마다 `g`, 부모 정보, frontier를 따로 유지하며, 다시 선택한 전략은 기존 상태를 이어갑니다. BFS는 가중 지형에서 최소 이동 횟수만 기준으로 하며 최소 비용을 보장하지 않습니다. 이동 비용은 **도착 칸 비용**이고 출발 칸 비용은 제외합니다.

최적 비용 C*는 평가용 무제한 Dijkstra만 계산합니다. 제어기는 C*를 받지 않습니다. `C ≤ ρh₀`를 품질 충분조건으로 사용하며, 이 조건이 불만족이어도 경로 품질이 나쁘다고 판정하지 않습니다.

## 결과 읽기

각 실험 폴더에 다음 파일을 생성합니다.

- `maps.jsonl`: 지도 전체, 시드, 분할, 실제 밀도, 평가용 최적 비용.
- `runs.jsonl`: 실행별 결과, 시간, 메모리, 경로 개선 기록, 선택·전환·반환 판단. 반복 유지 판단은 횟수로 요약합니다. 시뮬레이터 trace에서는 유지 판단도 모두 보존합니다.
- `results.csv`: Excel에서 열 수 있는 UTF-8 BOM 표.
- `manifest.json`: 설정, 고정 규칙, 환경, 코드 SHA-256.
- `summary.json`: 전체 지표와 짝지은 비교의 지도 단위 95% 신뢰구간.
- `summary_by_condition.csv`, `paired_by_condition.csv`: 예산·크기·구조·비용별 결과.
- `quality_success.svg`, `budget_quality.svg`, `controller_overhead.svg`: 분석 그래프.
- `report.md`, `report.html`: 실패를 포함한 실험 보고서.

최종 결과는 [초기 연구 보고서](docs/INITIAL_REPORT.md), [확장 예산 보고서](results/study/evaluation/report.md), [시간 제한 보고서](results/study/time_evaluation/report.md)에서 확인합니다. [원래 810개 조건 보고서](results/full/report.md)는 확장 실험에서 균일 비용 무작위 지도만 추출한 동일 실행 기록입니다. `python scripts/extract_original.py`로 다시 추출할 수 있습니다. HTML 보고서는 파일을 브라우저로 열면 됩니다. 소규모 계측 결과는 [smoke 보고서](results/smoke/report.md)에 있습니다.

도달률 및 Sρ의 분모는 **경로가 존재하는 모든 지도–예산 조합**입니다. 예산 내 미발견도 실패로 포함합니다. 경로 없는 지도는 별도로 보고합니다. 성공 사례의 평균 품질과 두 방법이 모두 성공한 사례의 품질 차이를 함께 계산합니다.

시간 제한은 Python에서 확장 전후로 확인하는 협력적 마감입니다. 초기화·한 확장·결과 정리 때문에 소폭 초과할 수 있으므로 초과 시간을 기록하고, 마감 후 완성한 새 경로를 채택하지 않습니다. 특징 계산·선택·전환·복원 및 계측 비용을 전체 시간에 포함하며 지도 생성, 최적 비용 평가, 애니메이션은 제외합니다.

기본 메모리 값은 여러 탐색기와 공통 방문 정보를 합친 **보존 상태 크기의 추정치**입니다. `profile_memory: true`인 설정은 `tracemalloc` allocation peak도 측정하며, 그 실행 시간에는 프로파일러 비용이 포함됩니다. 두 지표 모두 프로세스 전체 RSS는 아닙니다. 전체 평가의 속도 값과 계측 실험의 속도 값은 직접 혼합하지 않습니다.

설계와 한계는 [설계 문서](docs/ARCHITECTURE.md), [평가 프로토콜](docs/EXPERIMENT_PROTOCOL.md), [진행 현황](docs/PROGRESS.md)에 정리했습니다.

## 참고

ARA*의 OPEN/CLOSED/INCONS 재사용 구조는 [Likhachev, Gordon, Thrun (2003), ARA*](https://papers.nips.cc/paper_files/paper/2003/file/ee8fe9093fbbb687bef15a38facc44d2-Paper.pdf)의 Figure 3을 참고하여 구현했습니다. 예산 중간에 발견한 실행 가능한 경로도 보존하며, 인증된 가중치 경계와 중간의 실행 가능한 경로는 구분합니다. 선행 코드 저장소의 코드를 복사하지 않고 이 프로젝트에서 구현했습니다.
