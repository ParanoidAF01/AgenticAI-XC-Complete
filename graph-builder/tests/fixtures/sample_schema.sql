CREATE TABLE public.customers (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP
);

CREATE TABLE public.orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date DATE NOT NULL,
    total_amount DECIMAL(10, 2),
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES public.customers(id),
    CONSTRAINT chk_orders_amount CHECK (total_amount >= 0)
);

CREATE TABLE public.products (
    id INTEGER PRIMARY KEY,
    sku VARCHAR(50) NOT NULL UNIQUE,
    price DECIMAL(10, 2)
);

CREATE TABLE public.order_items (
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    CONSTRAINT pk_order_items PRIMARY KEY (order_id, product_id),
    CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES public.orders(id),
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES public.products(id)
);

CREATE TABLE public.audit_log (
    id INTEGER PRIMARY KEY,
    event_name VARCHAR(100),
    event_time TIMESTAMP
);

CREATE INDEX idx_orders_customer ON public.orders(customer_id);
CREATE INDEX idx_items_product ON public.order_items(product_id);
