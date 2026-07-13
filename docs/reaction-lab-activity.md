# 리액션 랩 Discord Activity 연결

`/리액션랩` 명령은 현재 봇과 같은 Discord Application에 연결된 Activity를 실행한다.

Discord Developer Portal에서 다음 설정이 필요하다.

1. 현재 봇 애플리케이션의 **Activities > Settings**에서 Activities를 활성화한다.
2. **Activities > URL Mappings**에 배포된 `discord-random-defense` 웹 주소를 `/` prefix로 등록한다.
3. 웹앱은 Discord iframe에서 실행될 때 자동으로 `REACTION LAB`만 표시한다.
4. 봇을 재배포한 뒤 서버에서 `/리액션랩`을 실행한다.

Activity가 활성화되지 않았거나 URL Mapping이 빠진 경우 명령은 사용자에게 설정 확인 안내를 표시한다.
