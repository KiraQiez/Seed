CREATE SCHEMA ecommerce;
CREATE TYPE ecommerce.order_status AS ENUM ('pending', 'shipped', 'cancelled');
CREATE TABLE ecommerce.customers (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email varchar(160) NOT NULL
);
CREATE TABLE ecommerce.products (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name varchar(80) NOT NULL,
    price numeric(10, 2) NOT NULL CHECK (price >= 0 AND price <= 10000)
);
CREATE TABLE ecommerce.orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES ecommerce.customers,
    status ecommerce.order_status NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE ecommerce.order_items (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES ecommerce.orders,
    product_id bigint NOT NULL REFERENCES ecommerce.products,
    quantity integer NOT NULL CHECK (quantity >= 1 AND quantity <= 100),
    UNIQUE (order_id, product_id)
);
CREATE TABLE ecommerce.payments (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES ecommerce.orders,
    amount numeric(10, 2) NOT NULL CHECK (amount >= 0 AND amount <= 10000)
);
