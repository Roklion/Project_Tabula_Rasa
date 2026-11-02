ALTER TABLE business_entities DROP CONSTRAINT ck_business_entities_currency;
ALTER TABLE business_entities ADD CONSTRAINT ck_business_entities_currency
    CHECK (currency_code IN ('USD', 'CAD'));

CREATE FUNCTION prevent_book_currency_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.currency_code IS DISTINCT FROM OLD.currency_code THEN
        RAISE EXCEPTION 'Book currency cannot change' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_book_currency BEFORE UPDATE OF currency_code ON business_entities
    FOR EACH ROW EXECUTE FUNCTION prevent_book_currency_change();
