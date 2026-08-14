"""Facade — 유일한 documented surface.

무엇을 담나
    dataset 등록, DataModel materialize, StrategyModel run, composition, report,
    extension 등록까지 user와 agent가 필요로 하는 모든 진입점을 하나의 import 경로로 노출한다.

무엇을 담지 않나
    경제 규칙과 계산. 여기는 재수출과 얇은 조립만 있고, 판단은 전부 층이 갖는다.

왜 이 파일이 존재하나
    `UC-FACADE-001`이 "installed documentation과 public API/CLI만으로 완주"를 요구한다. 내부
    module을 import하게 되는 순간 리팩터가 breaking change가 된다(architecture §2.6).

nautilus가 `config/`를 집계기로 둔 자리를 우리는 이 파일이 대신한다. 그래서 별도 `config`
package를 만들지 않는다(architecture §10).
"""
