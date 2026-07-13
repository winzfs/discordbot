# 리액션 랩 Discord Activity 연결

`/리액션랩` 명령은 현재 봇과 같은 Discord Application에 연결된 Activity를 실행한다.

Discord Developer Portal에서 다음 설정이 필요하다.

1. 현재 봇 애플리케이션의 **Activities > Settings**에서 Activities를 활성화한다.
2. 지원할 플랫폼에서 Desktop, Web, Android, iOS를 필요한 만큼 선택한다.
3. **Activities > URL Mappings**에 배포된 `discord-random-defense` 웹 주소를 `/` prefix로 등록한다.
4. 웹앱은 Discord iframe에서 실행될 때 홈과 다른 게임을 숨기고 `REACTION LAB`만 표시한다.
5. 봇을 재배포한 뒤 서버에서 `/리액션랩`을 실행한다.

## 정상 동작 확인

- 명령 실행 직후 Discord 내부 Activity 창이 열린다.
- 첫 화면부터 `REACTION LAB`이 표시된다.
- 게임 선택 화면으로 이동하는 뒤로가기 버튼은 보이지 않는다.
- 일반 브라우저에서 웹사이트를 열면 기존 홈과 다른 게임 메뉴는 그대로 유지된다.

Activity가 활성화되지 않았거나 URL Mapping이 빠진 경우 명령은 사용자에게 설정 확인 안내를 표시한다.
