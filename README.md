# Moba Quick Connect

MobaXterm에서 **Ctrl+Shift+Space**로 여는 Windows 세션 등록 도구입니다.

**[Install.cmd 다운로드](https://github.com/jja6312/moba-quick-connect/releases/latest/download/Install.cmd)**

CMD를 실행하면 현재 사용자 폴더에 설치합니다. Python과 관리자 권한은 필요하지 않습니다.
시작 메뉴의 **Moba Quick Connect**로 열 수 있습니다. 이전 도구가 실행 중이면 트레이에서 종료한 뒤 새 버전을 여세요.

## Windows 자동시작

MobaXterm에서 단축키를 받으려면 도구가 트레이에 실행 중이어야 합니다.
설치만으로 자동시작은 켜지지 않습니다. 필요한 사람만 아래 CMD를 실행하세요.

- [자동시작 켜기](https://github.com/jja6312/moba-quick-connect/releases/latest/download/Enable-Windows-Startup.cmd): Windows 로그인 후 트레이에서 실행
- [자동시작 끄기](https://github.com/jja6312/moba-quick-connect/releases/latest/download/Disable-Windows-Startup.cmd): 다음 로그인부터 자동 실행 해제

자동시작을 꺼도 저장한 기본값과 세션은 유지됩니다.
전달 폴더에서는 `Optional`에 두 CMD가 있습니다. 설치 자료는 `_support`에 모았습니다.

## 입력

- **연결 입력:** 한 개든 여러 개든 같은 표에 입력합니다. 기본값을 저장해 두고 IP만 입력해도 됩니다. 연결 이름을 비우면 IP로 만듭니다. Enter는 다음 연결의 같은 칸으로 이동합니다.
- **채우기 핸들:** 드래그하면 복사, Ctrl+드래그하면 IP나 끝 번호를 1씩 늘립니다.
- **Bastion:** 처음에는 접어 둡니다. **Alt+Enter**나 연결 이름 오른쪽 화살표로 개별 펼치기, **Bastion 모두 펼치기**로 전체 확인이 가능합니다. 접어도 입력한 값은 유지됩니다.
- **SSH/RDP:** 사용자, 포트, 키, 폴더와 점프 서버 기본값을 따로 저장합니다. 키 선택창은 모든 파일을 표시합니다.
- **즐겨찾는 키:** 별칭이나 경로 일부로 검색하면 가장 가까운 결과가 먼저 선택됩니다. **Enter**로 확정합니다. 즐겨찾는 키는 별칭으로, 미등록 키는 경로로 표시합니다. 실제 연결·복사·내보내기에는 원래 경로를 사용합니다. 폴더 버튼으로 새 키를 선택하면 즐겨찾기 등록 여부를 묻습니다.

상단 **즐겨찾는 키**에서 파일을 미리 등록하거나 이름을 바꾸고 목록에서 제거할 수 있습니다.
즐겨찾기는 키 파일의 이름과 경로만 현재 PC에 저장합니다.

이름 칸에서 **←**를 한 번 더 누르면 행 전체 선택으로 이동합니다. **Shift+↑/↓**로 여러 행을 선택하고 **→**로 이름 칸에 돌아옵니다. Ctrl+C는 숨겨진 Bastion까지 복사합니다.
상단 **테마 색상**에서 프리셋을 고르거나 **색상** 버튼으로 원하는 색을 지정합니다. 설정은 다음 실행에도 유지됩니다.

등록은 기존 MobaXterm 세션에 반영하며 자동 접속하지 않습니다. 필요하면 같은 설정으로 정상 재시작합니다.
MobaXterm은 별도로 설치해야 하며 이 프로그램에 포함되지 않습니다.

## 파일

프로그램은 `%LOCALAPPDATA%\Cloudragon\MobaQuickConnect`에 설치합니다.
기존 사용자 설정은 `%LOCALAPPDATA%\MobaQuickConnect`를 계속 사용합니다.
일반 등록과 즐겨찾기는 키 경로만 저장합니다. **내보내기 (키 포함)**를 선택하면 해당 연결에서 사용하는 키 파일도 ZIP에 담습니다.
공유 게시 충돌과 미완료 편집은 덮어쓰지 않고 표시합니다. 변경 전 백업을 보관합니다.

기존 공유 실행기의 `unfinished edit` 경고 복구 코드는
[shared-launcher](windows/shared-launcher/README.md)에 있습니다.
변경 없이 남은 기록만 백업 후 보관하며, 실제 편집 내용은 보호합니다.
이 코드는 기존 공유 실행기용 유지보수 자료입니다.

## 다른 PC로 옮기기

**내보내기 (키 포함)**로 `.mobaquick.zip`을 저장하고 다른 PC의 Moba Quick Connect에서 **가져오기**를 누릅니다.
키 파일을 새 PC의 로컬 폴더에 보관하고 연결 경로와 즐겨찾기를 맞춥니다. 입력 표를 확인한 뒤 **일괄 추가**를 누르세요.
내보낸 ZIP은 암호화되지 않았으며 개인 키가 들어 있으므로 안전한 위치에 보관하세요.
CSV와 MobaXterm 세션 파일 내보내기는 키 파일을 포함하지 않습니다.

연결 이름과 IP의 앞뒤 공백·줄바꿈은 제거합니다. 행 번호를 클릭하거나 드래그하면 연결 전체를 선택하며, Ctrl+C로 숨긴 Bastion까지 복사합니다.

## 개발

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe -m pip install pyinstaller==6.22.3
.venv\Scripts\python.exe build.py
.venv\Scripts\python.exe build_installer.py
```

설치기는 Windows PowerShell 5.1과 CMD에서 임시 설치 폴더로 검증합니다.
GUI 시험은 가상 IP를 사용하며 고객 서버에 접속하지 않습니다.
실제 RDP 인증과 Bastion 종단 접속은 별도 환경에서 확인해야 합니다.
구성 요소 라이선스는 [THIRD_PARTY.txt](THIRD_PARTY.txt)와 `release-resources`를 참고하세요.
