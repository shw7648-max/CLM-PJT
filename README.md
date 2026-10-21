# GoTruck Marketing Content Studio

이 폴더는 Streamlit Community Cloud 배포용 독립 패키지입니다. **이 폴더의 내용만 GitHub 저장소 루트에 올리면** 실행할 수 있도록 구성했습니다.

## Streamlit Community Cloud 배포

1. `streamlit_cloud_deploy` 폴더 안의 파일을 GitHub 저장소 루트에 올립니다.
2. Streamlit Community Cloud에서 **Create app**을 선택하고 해당 저장소·브랜치를 지정합니다.
3. 앱 진입점은 `app.py`로 설정합니다.
4. **Advanced settings → Secrets**에 실제 API 키를 입력합니다.

   ```toml
   OPENAI_API_KEY = "실제_OpenAI_API_키"
   ```

5. Python 버전은 **3.12**를 선택해 배포합니다.

실제 API 키를 코드나 저장소에 넣지 마세요. Cloud 앱은 설정의 Secrets에서 키를 읽습니다. 키를 바꿀 때도 앱 설정의 Secrets에서 갱신하세요.

## 로컬 실행

1. Python 3.12를 설치합니다.
2. `.env.example`을 `.env`로 복사하고 `OPENAI_API_KEY` 값을 입력합니다.
3. Windows에서는 `run.bat`을 더블클릭합니다.

## 패키지 파일

```text
app.py                     앱 진입점
requirements.txt           고정된 Python 의존성
.streamlit/config.toml     테마 및 서버 설정
.env.example               로컬 키 설정 예시 (실제 키 없음)
.gitignore                 키·가상환경 제외 규칙
run.bat                    Windows 로컬 실행 도우미
README.md                  배포 및 실행 안내
```

앱은 GPT-6 Luna를 사용해 카피를 생성하고 카카오 브랜드톡 PNG 시안을 만듭니다. 생성 결과와 사전 점검은 기획 보조용으로, 배포 전 사실관계와 내부 광고 심의를 확인해야 합니다.
