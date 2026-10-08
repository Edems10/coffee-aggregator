-- `catalogue_reader`: the one definition of "may look at the catalogue, may not
-- change it". The table browser sits behind a proxy on the open internet and
-- connected as `coffee`, the owning role, which is a DROP TABLE away from the
-- data it exists to display; Grafana's dashboards had the same need and were
-- answered with a hand-run snippet in another repository, which is how two
-- read-only roles drift apart.
--
-- It is NOLOGIN on purpose: a role in a migration must carry no credential, and
-- a group role carries none. Each consumer gets its own LOGIN role with its own
-- password, created by the operator and granted membership here -- see "The
-- table browser" in deploy/README.md. One password per consumer means rotating
-- the browser's credential does not blank the dashboards.

-- Roles are cluster-wide while privileges are per-database, so this same file
-- runs against `coffee` and `coffee_test` on one cluster and must find the role
-- already there the second time.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalogue_reader') THEN
        CREATE ROLE catalogue_reader NOLOGIN;
    END IF;
END
$$;

-- The database is named by DATABASE_URL, never by this file: `coffee` on the
-- server, `coffee_test` under pytest, something else on a managed Postgres.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO catalogue_reader', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO catalogue_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO catalogue_reader;

-- SELECT on every table is not the same as "cannot write". PostgreSQL before 15
-- gave CREATE on `public` to PUBLIC, and a database carried from such a cluster
-- keeps that ACL however new the server is -- the development cluster here is
-- 15 and still has it, which is how this was found: the reader could not touch
-- a single existing row and could still CREATE TABLE beside them. Postgres 15
-- made this the default; saying it out loud makes every database the same one.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- The half that silently rots. `ALL TABLES` above is a snapshot: it grants on
-- the tables that exist at this instant and knows nothing about the next
-- migration, and migrations numbered below this one can still be applied after
-- it -- 0004 and 0005 were being written in parallel with 0006 and may well
-- land on a server that already ran this file. Default privileges are the
-- standing instruction that covers both cases without anyone remembering to
-- re-grant.
--
-- Deliberately no FOR ROLE: default privileges attach to the role that creates
-- the object, and leaving it off means "whoever is running this migration",
-- which is the role in DATABASE_URL and therefore also the role that will
-- create every future table. Naming the owner here would hard-code `coffee`
-- and quietly stop working on a database whose owner is called something else.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO catalogue_reader;
