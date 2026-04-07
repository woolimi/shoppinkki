# DB 초기화 / LLM(벡터) 데이터 주의사항

이 프로젝트는 `docker-compose.yml`의 MySQL 컨테이너에서 아래 SQL들을 **DB 초기화 시점**에 실행합니다.

- `schema.sql` → 테이블 생성
- `seed_data.sql` → 기본 시드 데이터(ZONE/PRODUCT/PRODUCT_TEXT_EMBEDDING 등)

## 중요한 포인트: SQL을 수정해도 자동 반영되지 않습니다

MySQL은 `mysql_data` 볼륨을 사용합니다. 이미 볼륨이 생성된 상태에서는
`/docker-entrypoint-initdb.d/*.sql`이 **다시 실행되지 않기 때문에**,
`schema.sql`/`seed_data.sql`을 수정해도 DB에 자동 반영되지 않습니다.

### 초기화(데이터 삭제)로 다시 반영

```bash
docker compose down -v
docker compose up -d
```

### 데이터 유지한 채로 적용(수동 실행)

```bash
docker exec -i shoppinkki_mysql mysql -ushoppinkki -pshoppinkki shoppinkki < scripts/db/schema.sql
docker exec -i shoppinkki_mysql mysql -ushoppinkki -pshoppinkki shoppinkki < scripts/db/seed_data.sql
```

## 임베딩 채우기 스크립트

`PRODUCT_TEXT_EMBEDDING.embedding`은 MySQL `VECTOR(384)`이며, 시드 단계에서는 `NULL`로 들어갑니다.
임베딩 값은 아래 스크립트가 **UPDATE**로 채웁니다(테이블 생성은 하지 않음).

```bash
python3 scripts/db/fill_product_embeddings.py
```

- **사용 모델**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384차원)

