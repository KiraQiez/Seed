# Seed guide

Generate **10 fake customers** in a PostgreSQL development or test database. You can preview the rows, save them to files, or insert them into PostgreSQL.

## Before you start

Install Seed with `uv tool install seed-dev-db`, `pipx install seed-dev-db`, or `brew install KiraQiez/tap/seed` on supported platforms. Run `seed --version` to check that your terminal can find it. See the [installation options](README.md#install).

Use an existing `public.customers` table. If you want to insert the rows, start with the table empty. If you need a database and table to practice with, [start a disposable PostgreSQL database](#start-a-disposable-database).

## 1. Connect and select a table

Run guided setup from your project directory if `seed init --help` lists `--interactive`.

```sh
seed init --interactive
```

Press Enter for the `public` schema, enter `customers`, then press Enter to accept **10** rows. Press Enter again to finish and save `seed.toml`.

For Seed 0.1.0 or manual setup, run `seed init` and add these lines to the end of `seed.toml`.

```toml
[tables.customers]
rows = 10
```

If the table lives in another schema, set `schema` in the file's existing `[database]` section.

Set the database URL in the same terminal you'll use to run Seed. The example URL works with the disposable database below. Use your own URL for an existing database.

**macOS and Linux**

```sh
export DATABASE_URL='postgresql://seed_user:seed_demo_password@127.0.0.1:55432/seed_demo'
```

**PowerShell**

```powershell
$env:DATABASE_URL = 'postgresql://seed_user:seed_demo_password@127.0.0.1:55432/seed_demo'
```

Keep your real password in the connection variable. `seed.toml` stores the variable's name. [Connection reference](docs/SECURITY.md#connection-and-credentials)

## 2. See what Seed will generate

```sh
seed plan
seed preview --limit 3
seed validate --dataset
```

`plan` lists the tables and expected row counts. Look for **10 planned rows**. `preview` shows three sample rows. `validate --dataset` checks all 10 rows. These commands leave the database unchanged. When a selected table references another table, the plan also shows the required tables.

## 3. Save the rows to files

```sh
seed export --format json
```

Open `seed-export/dataset.json` to see the generated rows. The `manifest.json` file lists what was written. Export leaves the database unchanged. Choose `sql` or `csv` if you need those formats. For another export, give `--output` a fresh directory name. [Import instructions](docs/SECURITY.md#sql-and-export-safety)

## 4. Insert the rows into PostgreSQL

To use the rows in your test database, add the settings below to `seed.toml`. Match the host, port, database name, and schema to your own connection.

```toml
[safety]
environment = "test"

[safety.target]
host = "127.0.0.1"
port = 55432
database = "seed_demo"
schema = "public"
```

```sh
seed apply --dry-run
seed apply
```

Check the database name and planned row count in the dry-run. Then run `seed apply` and type `y` when prompted. Expect **Committed 10 rows**. You can confirm the result with `SELECT count(*) FROM public.customers;` in your PostgreSQL client. [Apply safety](docs/SECURITY.md#apply-safety)

## Start a disposable database

Use Docker on macOS or Linux and run these commands in a new working directory. This example uses local port 55432.

```sh
docker run --rm -d --name seed-guide \
  -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=seed_user \
  -e POSTGRES_PASSWORD=seed_demo_password \
  -e POSTGRES_DB=seed_demo postgres:17

docker exec seed-guide pg_isready -h 127.0.0.1 -U seed_user -d seed_demo
```

Rerun the readiness command until it says PostgreSQL is accepting connections. Then create the empty test table.

```sh
docker exec -i seed-guide psql -U seed_user -d seed_demo -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE public.customers (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email varchar(160) NOT NULL
);
SQL
```

Return to step 1. To remove the disposable database when finished, run `docker stop seed-guide`.

## Common problems

| What happened | What to check |
| --- | --- |
| Seed can't read the config or find the connection variable | Run from the folder containing `seed.toml`. Set the variable named by `database.url_env` in your current terminal. |
| Seed can't connect | Check that PostgreSQL is running and that the URL has the right host, port, database, and credentials. |
| Apply refuses the target | Compare the URL and selected schema with `[safety.target]`, then rerun the dry-run. |
| Apply says the table already has rows | Use an empty test table or choose export to save rows to files. |
| The export folder already exists | Try `seed export --format json --output ./seed-export-2`. |
