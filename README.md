# 인천효성고 공지 자동 수집 사이트 올리기

기존 학교 정보 화면은 유지하고 공지사항과 가정통신문을 실제 학교 게시판에서 가져오는 묶음입니다. 공지는 최근 1년치를 대상으로 합니다. Gemini나 다른 AI를 켜두지 않아도 GitHub Actions가 수집 프로그램을 실행합니다.

## 1. 올릴 파일

ZIP을 풀면 다음 파일이 있습니다. 기존 저장소의 최상위 위치에 파일과 폴더 구조를 맞춰 올립니다.

```text
index.html
notices.json
collect_notices.py
requirements.txt
README.md
.gitignore
tests/
  test_collect_notices.py
.github/
  workflows/
    update-notices.yml
```

- index.html: 기존 화면에 실제 공지 파일을 읽는 기능을 추가한 파일입니다. 파일 이름은 소문자 index.html을 사용합니다.
- notices.json: 실제 게시글 목록과 마지막 성공 시각입니다. Actions가 자동으로 갱신합니다.
- collect_notices.py: 두 학교 게시판을 읽는 수집 프로그램입니다.
- requirements.txt: 수집 프로그램에 필요한 Python 라이브러리 목록입니다.
- .github/workflows/update-notices.yml: 수집, 공지 파일 저장, 사이트 배포를 실행하는 설정입니다.
- tests 폴더: 필요할 때 수집 동작과 실패 시 이전 목록 보존을 점검하는 테스트입니다.

원본 HTML 파일은 별도로 보관해두세요. GitHub에 ZIP 파일 하나를 올리는 대신 압축을 푼 안의 파일들을 올립니다.

## 2. 이미 사용 중인 GitHub 저장소에 올리기

1. GitHub에서 지금 사이트를 올려둔 저장소를 엽니다.
2. Code 화면의 기본 브랜치를 선택합니다. 보통 main이지만 다른 이름이어도 됩니다.
3. Add file → Upload files를 누릅니다.
4. index.html, notices.json, collect_notices.py, requirements.txt, README.md, .gitignore를 저장소 최상위에 올리고 Commit changes를 누릅니다. 기존 index.html은 이 파일로 교체합니다.
5. tests 폴더도 올려두면 이후 점검에 사용할 수 있습니다.
6. 워크플로 폴더 업로드가 어렵다면 Add file → Create new file을 누릅니다.
7. 파일 이름에 아래 경로 전체를 입력합니다.

```text
.github/workflows/update-notices.yml
```

8. ZIP 안에 있는 update-notices.yml을 텍스트 편집기로 열어 전체 내용을 복사하고 GitHub 편집기에 붙여넣습니다.
9. Commit changes로 기본 브랜치에 저장합니다.

파일들이 한 단계 더 깊은 폴더에 들어가지 않도록 확인하세요. Code 화면에서 index.html과 notices.json이 바로 보여야 합니다.

## 3. Pages 배포 방식을 변경하기

1. 저장소의 Settings를 누릅니다.
2. 왼쪽 메뉴에서 Pages를 선택합니다.
3. Build and deployment의 Source를 GitHub Actions로 바꿉니다.

이 묶음은 수집한 파일을 Pages에 직접 배포합니다. 이전의 Deploy from a branch 설정을 GitHub Actions로 바꾸는 단계가 필요합니다. 워크플로에는 공지 파일 저장과 Pages 배포에 필요한 권한이 명시되어 있습니다. 별도 학교 API 키나 개인 GitHub 토큰을 입력할 필요는 없습니다.

## 4. 처음 한 번 수동 실행하기

1. 저장소 상단의 Actions를 누릅니다.
2. 첫 사용 시 Actions 활성화 안내가 보이면 활성화합니다.
3. 왼쪽의 Update school notices and deploy Pages를 선택합니다.
4. Run workflow를 눌러 기본 브랜치에서 실행합니다.
5. 새 실행 기록을 열고 수집과 배포 결과를 확인합니다.
6. 완료되면 Settings → Pages에 표시된 사이트 주소를 엽니다.
7. 학교 공지사항 탭에서 마지막 수집 시각과 글 목록을 확인합니다. 공지 종류와 검색도 사용해보세요.
8. 원문 버튼을 누르면 게시판 목록이 아닌 해당 학교 게시글로 이동해야 합니다.

Actions는 기본 브랜치의 사이트 파일을 갱신했을 때도 실행합니다. Pages 설정을 바꾸기 전에 실행되어 실패한 기록이 있다면 설정을 바꾼 뒤 Run workflow로 다시 실행하세요.

## 5. 자동 갱신 시간과 실패 처리

한국 시간 기준 매일 08:17, 12:17, 18:17에 수집하도록 설정합니다. 예약 실행은 GitHub 상황에 따라 늦어질 수 있습니다. 수집한 시점의 자료를 보여주며 새 공지는 다음 수집 뒤에 반영됩니다. 화면의 마지막 성공 시각을 기준으로 확인하세요.

두 게시판의 수집이 모두 성공하면 공지 파일을 교체합니다. 어느 한쪽이라도 실패하면 이전 정상 목록과 마지막 성공 시각을 유지하고 이번 시도의 실패 상태를 저장합니다. 화면에는 이전 자료를 표시하고 있다는 안내가 나옵니다. 실패 상태를 사이트에 배포한 뒤 Actions 실행도 실패로 표시하므로 기록에서 원인을 확인할 수 있습니다.

처음부터 정상 자료가 없는 경우에는 수집 실패 안내와 학교 게시판 링크를 표시합니다. 확인하지 않은 공지 제목, 본문, 작성자, 조회수는 생성하지 않습니다.

사이트를 이미 열어두었다면 새로고침해 새 공지 파일을 읽어오세요. 방문자의 새로고침은 학교 수집 프로그램을 실행하는 버튼이 아닙니다. 최신 수집은 Actions의 예약 실행이나 Run workflow로 이루어집니다.

## 6. 문제가 생겼을 때

- 사이트는 열리는데 공지 파일을 못 읽는 경우: index.html과 notices.json이 같은 최상위 위치에 있는지, 최신 워크플로 배포가 완료되었는지 확인합니다.
- 수집 단계에서 실패한 경우: Actions 실행 기록에서 Collect notices 단계를 엽니다. 학교 서버가 GitHub 실행 환경의 접속을 거절했는지, 응답 구조가 바뀌었는지 오류 내용을 확인합니다.
- 공지 파일 저장에서 권한 오류가 난 경우: 워크플로의 contents: write 권한과 저장소 또는 조직의 Actions 정책, 기본 브랜치 보호 규칙을 확인합니다. 보호 규칙을 임의로 해제하지 말고 소유자와 필요한 쓰기 권한을 확인합니다.
- Pages 배포가 실패한 경우: Settings → Pages → Source가 GitHub Actions인지 확인합니다. github-pages 환경의 배포 허용 브랜치가 현재 기본 브랜치와 맞는지도 확인합니다.
- 일정 시간이 지났는데 갱신되지 않는 경우: Actions 실행 기록과 워크플로 활성화 상태를 확인합니다. 공지 목록의 마지막 성공 시각도 함께 확인합니다.
- 파일을 더블클릭했을 때 공지를 못 읽는 경우: 이 버전은 Pages 같은 HTTP/HTTPS 주소로 여는 용도입니다. 로컬에서도 아래 서버 방식으로 열 수 있습니다.

## 7. 내 컴퓨터에서 확인하기

Python이 설치되어 있다면 압축을 푼 폴더에서 다음 명령을 실행합니다.

```sh
python -m pip install -r requirements.txt
python collect_notices.py
python -m http.server 8000
```

브라우저에서 http://localhost:8000 을 엽니다. 웹 서버를 종료할 때는 터미널에서 Ctrl+C를 누릅니다.

수집 테스트를 직접 실행하려면 다음 명령을 사용합니다.

```sh
python -m unittest discover -s tests -v
```

## 확인 범위

이 묶음은 제공받은 HTML을 기준으로 만들었습니다. 실제 학생의 GitHub 계정 업로드, GitHub Actions 실행, Pages 배포 결과는 아직 확인하지 않았습니다. 로컬 수집 성공만으로 GitHub 실행 환경에서도 학교 서버에 접근할 수 있다고 보장하지 않으며 첫 수동 실행에서 확인해야 합니다.

## 공식 자료

- [학교 공지사항](https://in-hyoseong.icehs.kr/boardCnts/list.do?boardID=3202&m=0209&s=in_hyoseong)
- [학교 가정통신문](https://in-hyoseong.icehs.kr/boardCnts/list.do?boardID=3215&m=0201&s=in_hyoseong)
- [GitHub Pages 게시 방식 설정](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [Actions로 Pages 배포](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Actions 예약 실행](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
