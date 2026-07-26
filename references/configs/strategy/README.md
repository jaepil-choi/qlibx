# Strategy overrides

이 directory는 strategy family별 production override만 둔다. Strategy class와
factory default가 그대로 쓰이는 peer momentum, open-close, factor strategy는 빈
YAML block을 만들지 않는다. 새 override가 생기면 `peer_momentum.yaml`,
`open_close.yaml`, `signals.yaml`, `masks.yaml` 중 책임에 맞는 fragment에 추가한다.
