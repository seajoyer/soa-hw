FROM python:3.12-slim AS codegen
RUN pip install --no-cache-dir fastapi-code-generator==0.8.1
WORKDIR /src
COPY openapi openapi
COPY codegen codegen
RUN fastapi-codegen -i openapi/openapi.yaml -o generated -t codegen -p 3.12 --strict-nullable --disable-timestamp --include-request-argument

FROM python:3.12-slim
WORKDIR /service
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY --from=codegen /src/generated app/generated
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
