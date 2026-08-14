"""CLI 진입점.

구현할 것
    main()   `[project.scripts]`의 `vqapr = "vqapr.cli:main"`이 가리키는 함수
    서브명령 등록과 dispatch

여기서 하지 않을 것
    경제 규칙. 각 명령 파일이 `public.py`를 통해 층을 부른다.
    **user에게 질문하지 않는다** — package는 deterministic하고 대화는 agent skill이 담당한다
    (PRD §2.6). CLI는 인자를 받아 판정 결과를 낸다.
"""
