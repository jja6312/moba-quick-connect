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

- **단건:** 기본값을 저장해 두고 IP를 입력합니다. 연결 이름을 비우면 IP로 만듭니다.
- **일괄:** Excel의 여러 셀을 붙여넣고 수정합니다. Enter는 다음 연결의 같은 칸으로 이동합니다.
- **채우기 핸들:** 드래그하면 복사, Ctrl+드래그하면 IP나 끝 번호를 1씩 늘립니다.
- **Bastion:** 연결 바로 아래 보라색 행에 입력합니다. 해당 행의 Enter는 다음 Bastion으로 이동합니다.
- **SSH/RDP:** 사용자, 포트, 키, 폴더와 점프 서버 기본값을 따로 저장합니다. 키 선택창은 모든 파일을 표시합니다.

등록은 기존 MobaXterm 세션에 반영하며 자동 접속하지 않습니다. 필요하면 같은 설정으로 정상 재시작합니다.
MobaXterm은 별도로 설치해야 하며 이 프로그램에 포함되지 않습니다.

## 파일

프로그램은 `%LOCALAPPDATA%\Cloudragon\MobaQuickConnect`에 설치합니다.
기존 사용자 설정은 `%LOCALAPPDATA%\MobaQuickConnect`를 계속 사용합니다.
키 파일은 경로만 저장하며 내용이나 비밀번호를 읽지 않습니다.
공유 게시 충돌과 미완료 편집은 덮어쓰지 않고 표시합니다. 변경 전 백업을 보관합니다.

기존 공유 실행기의 `unfinished edit` 경고 복구 코드는
[shared-launcher](windows/shared-launcher/README.md)에 있습니다.
변경 없이 남은 기록만 백업 후 보관하며, 실제 편집 내용은 보호합니다.
이 코드는 기존 공유 실행기용 유지보수 자료입니다.

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
