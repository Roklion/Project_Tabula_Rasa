-- Frozen ADR 0001 baseline. Change the schema with a new revision, never edit a deployed baseline.

CREATE TABLE business_entities (
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    name text NOT NULL,
    currency_code text NOT NULL DEFAULT 'USD',
    CONSTRAINT pk_business_entities PRIMARY KEY (id),
    CONSTRAINT ck_business_entities_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_business_entities_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_business_entities_version CHECK (version > 0),
    CONSTRAINT ck_business_entities_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_business_entities_currency CHECK (currency_code = 'USD')
);

CREATE TABLE accounts (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    name text NOT NULL,
    name_key text COLLATE "C" NOT NULL,
    type text NOT NULL,
    classification text NOT NULL,
    opening_balance numeric(28,2) NOT NULL DEFAULT 0,
    active boolean NOT NULL DEFAULT true,
    parent_id text,
    CONSTRAINT pk_accounts PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_accounts_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_accounts_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_accounts_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_accounts_version CHECK (version > 0),
    CONSTRAINT ck_accounts_opening_balance_finite CHECK (opening_balance <> 'NaN'::numeric),
    CONSTRAINT ck_accounts_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_accounts_name_key CHECK (btrim(name_key) <> ''),
    CONSTRAINT ck_accounts_type CHECK (type IN ('Bank','Cash','Credit card','Short-term debt','Equity','Other')),
    CONSTRAINT ck_accounts_classification CHECK (classification IN ('Asset','Liability','Equity')),
    CONSTRAINT ck_accounts_type_classification CHECK ((type IN ('Bank','Cash') AND classification = 'Asset') OR (type IN ('Credit card','Short-term debt') AND classification = 'Liability') OR (type = 'Equity' AND classification = 'Equity') OR type = 'Other'),
    CONSTRAINT ck_accounts_parent CHECK (parent_id <> id),
    CONSTRAINT fk_accounts_parent_id FOREIGN KEY (entity_id, parent_id) REFERENCES accounts (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_accounts_name_key UNIQUE (entity_id, name_key)
);

CREATE INDEX ix_accounts_parent_id ON accounts (entity_id, parent_id);

CREATE TABLE categories (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    name text NOT NULL,
    name_key text COLLATE "C" NOT NULL,
    kind text NOT NULL,
    parent_id text,
    CONSTRAINT pk_categories PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_categories_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_categories_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_categories_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_categories_version CHECK (version > 0),
    CONSTRAINT ck_categories_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_categories_name_key CHECK (btrim(name_key) <> ''),
    CONSTRAINT ck_categories_kind CHECK (kind IN ('Income','Expense')),
    CONSTRAINT ck_categories_parent CHECK (parent_id <> id),
    CONSTRAINT fk_categories_parent_id FOREIGN KEY (entity_id, parent_id) REFERENCES categories (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_categories_kind_name_key UNIQUE (entity_id, kind, name_key)
);

CREATE INDEX ix_categories_parent_id ON categories (entity_id, parent_id);

CREATE TABLE payees (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    name text NOT NULL,
    name_key text COLLATE "C" NOT NULL,
    active boolean NOT NULL DEFAULT true,
    CONSTRAINT pk_payees PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_payees_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_payees_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_payees_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_payees_version CHECK (version > 0),
    CONSTRAINT ck_payees_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_payees_name_key CHECK (btrim(name_key) <> ''),
    CONSTRAINT uq_payees_name_key UNIQUE (entity_id, name_key)
);

CREATE TABLE tags (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    name text NOT NULL,
    name_key text COLLATE "C" NOT NULL,
    active boolean NOT NULL DEFAULT true,
    CONSTRAINT pk_tags PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_tags_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_tags_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_tags_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_tags_version CHECK (version > 0),
    CONSTRAINT ck_tags_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_tags_name_key CHECK (btrim(name_key) <> ''),
    CONSTRAINT uq_tags_name_key UNIQUE (entity_id, name_key)
);

CREATE TABLE entries (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    txn_date date NOT NULL,
    projection_kind text NOT NULL,
    simple_kind text,
    description text NOT NULL DEFAULT '',
    reference text NOT NULL DEFAULT '',
    payee_id text,
    mixed_use_source_id text,
    depreciation_asset_id text,
    CONSTRAINT pk_entries PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_entries_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_entries_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_entries_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_entries_version CHECK (version > 0),
    CONSTRAINT ck_entries_projection CHECK (projection_kind IN ('simple','journal')),
    CONSTRAINT ck_entries_simple_kind CHECK ((projection_kind = 'simple' AND simple_kind IS NOT NULL AND simple_kind IN ('Income','Expense','Transfer')) OR (projection_kind = 'journal' AND simple_kind IS NULL)),
    CONSTRAINT ck_entries_journal_metadata CHECK (projection_kind <> 'journal' OR (payee_id IS NULL AND mixed_use_source_id IS NULL AND depreciation_asset_id IS NULL AND reference = '')),
    CONSTRAINT ck_entries_owner CHECK (num_nonnulls(mixed_use_source_id,depreciation_asset_id) <= 1 AND ((mixed_use_source_id IS NULL AND depreciation_asset_id IS NULL) OR simple_kind = 'Expense')),
    CONSTRAINT fk_entries_payee_id FOREIGN KEY (entity_id, payee_id) REFERENCES payees (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_entries_id_projection_kind UNIQUE (entity_id, id, projection_kind)
);

CREATE INDEX ix_entries_payee_id ON entries (entity_id, payee_id);

CREATE UNIQUE INDEX uq_entries_mixed_source ON entries(entity_id,mixed_use_source_id) WHERE mixed_use_source_id IS NOT NULL;

CREATE INDEX ix_entries_date ON entries (entity_id, txn_date, id);

CREATE INDEX ix_entries_projection_date ON entries (entity_id, projection_kind, txn_date, id);

CREATE INDEX ix_entries_depreciation_asset ON entries (entity_id, depreciation_asset_id);

CREATE TABLE postings (
    entity_id text NOT NULL,
    id text NOT NULL,
    entry_id text NOT NULL,
    projection_kind text NOT NULL,
    position integer NOT NULL,
    account_id text,
    category_id text,
    side text NOT NULL,
    amount numeric(28,2) NOT NULL,
    payee_id text,
    description text NOT NULL DEFAULT '',
    CONSTRAINT pk_postings PRIMARY KEY (entity_id, projection_kind, id),
    CONSTRAINT fk_postings_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_postings_amount_finite CHECK (amount <> 'NaN'::numeric),
    CONSTRAINT ck_postings_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_postings_position CHECK (position > 0),
    CONSTRAINT ck_postings_target CHECK (num_nonnulls(account_id,category_id) = 1),
    CONSTRAINT ck_postings_side CHECK (side IN ('Debit','Credit')),
    CONSTRAINT ck_postings_amount CHECK (amount >= 0),
    CONSTRAINT fk_postings_account_id FOREIGN KEY (entity_id, account_id) REFERENCES accounts (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_postings_category_id FOREIGN KEY (entity_id, category_id) REFERENCES categories (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_postings_payee_id FOREIGN KEY (entity_id, payee_id) REFERENCES payees (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_postings_entry_id_position UNIQUE (entity_id, entry_id, position)
);

CREATE INDEX ix_postings_account_id ON postings (entity_id, account_id);

CREATE INDEX ix_postings_category_id ON postings (entity_id, category_id);

CREATE INDEX ix_postings_payee_id ON postings (entity_id, payee_id);

ALTER TABLE postings ADD CONSTRAINT fk_postings_entry FOREIGN KEY (entity_id,entry_id,projection_kind) REFERENCES entries(entity_id,id,projection_kind) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX ix_postings_account_entry ON postings (entity_id, account_id, entry_id);

CREATE INDEX ix_postings_category_entry ON postings (entity_id, category_id, entry_id);

CREATE TABLE entry_tags (
    entity_id text NOT NULL,
    entry_id text NOT NULL,
    tag_id text NOT NULL,
    CONSTRAINT pk_entry_tags PRIMARY KEY (entity_id, entry_id, tag_id),
    CONSTRAINT fk_entry_tags_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT fk_entry_tags_entry_id FOREIGN KEY (entity_id, entry_id) REFERENCES entries (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_entry_tags_tag_id FOREIGN KEY (entity_id, tag_id) REFERENCES tags (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_entry_tags_entry_id ON entry_tags (entity_id, entry_id);

CREATE INDEX ix_entry_tags_tag_id ON entry_tags (entity_id, tag_id);

CREATE INDEX ix_entry_tags_reverse ON entry_tags (entity_id, tag_id, entry_id);

CREATE TABLE mixed_use_sources (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    txn_date date NOT NULL,
    total_expense numeric(28,2) NOT NULL,
    business_use_percentage numeric(8,5) NOT NULL,
    allocated_amount numeric(28,2) NOT NULL,
    account_id text NOT NULL,
    category_id text NOT NULL,
    payee_id text,
    description text NOT NULL DEFAULT '',
    reference text NOT NULL DEFAULT '',
    allocation_rationale text NOT NULL,
    expected_projection_entry_id text NOT NULL,
    relationship_state text NOT NULL DEFAULT 'complete',
    CONSTRAINT pk_mixed_use_sources PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_mixed_use_sources_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_mixed_use_sources_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_mixed_use_sources_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_mixed_use_sources_version CHECK (version > 0),
    CONSTRAINT ck_mixed_use_sources_total_expense_finite CHECK (total_expense <> 'NaN'::numeric),
    CONSTRAINT ck_mixed_use_sources_business_use_percentage_finite CHECK (business_use_percentage <> 'NaN'::numeric),
    CONSTRAINT ck_mixed_use_sources_allocated_amount_finite CHECK (allocated_amount <> 'NaN'::numeric),
    CONSTRAINT ck_mixed_use_sources_allocation_rationale CHECK (btrim(allocation_rationale) <> ''),
    CONSTRAINT ck_mixed_use_sources_expected_projection_entry_id CHECK (btrim(expected_projection_entry_id) <> ''),
    CONSTRAINT ck_mixed_use_sources_allocation CHECK (total_expense > 0 AND allocated_amount > 0 AND allocated_amount <= total_expense),
    CONSTRAINT ck_mixed_use_sources_percentage CHECK (business_use_percentage > 0 AND business_use_percentage <= 100),
    CONSTRAINT ck_mixed_use_sources_state CHECK (relationship_state IN ('complete','missing_projection','projection_mismatch')),
    CONSTRAINT fk_mixed_use_sources_account_id FOREIGN KEY (entity_id, account_id) REFERENCES accounts (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_mixed_use_sources_category_id FOREIGN KEY (entity_id, category_id) REFERENCES categories (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_mixed_use_sources_payee_id FOREIGN KEY (entity_id, payee_id) REFERENCES payees (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_mixed_use_sources_expected_projection_entry_id UNIQUE (entity_id, expected_projection_entry_id)
);

CREATE INDEX ix_mixed_use_sources_account_id ON mixed_use_sources (entity_id, account_id);

CREATE INDEX ix_mixed_use_sources_category_id ON mixed_use_sources (entity_id, category_id);

CREATE INDEX ix_mixed_use_sources_payee_id ON mixed_use_sources (entity_id, payee_id);

CREATE INDEX ix_mixed_use_sources_date ON mixed_use_sources (entity_id, txn_date, id);

CREATE TABLE mixed_use_tags (
    entity_id text NOT NULL,
    source_id text NOT NULL,
    tag_id text NOT NULL,
    CONSTRAINT pk_mixed_use_tags PRIMARY KEY (entity_id, source_id, tag_id),
    CONSTRAINT fk_mixed_use_tags_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT fk_mixed_use_tags_source_id FOREIGN KEY (entity_id, source_id) REFERENCES mixed_use_sources (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_mixed_use_tags_tag_id FOREIGN KEY (entity_id, tag_id) REFERENCES tags (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_mixed_use_tags_source_id ON mixed_use_tags (entity_id, source_id);

CREATE INDEX ix_mixed_use_tags_tag_id ON mixed_use_tags (entity_id, tag_id);

CREATE INDEX ix_mixed_use_tags_reverse ON mixed_use_tags (entity_id, tag_id, source_id);

ALTER TABLE entries ADD CONSTRAINT fk_entries_mixed_use_source FOREIGN KEY (entity_id,mixed_use_source_id) REFERENCES mixed_use_sources(entity_id,id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE recurring_schedules (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    name text NOT NULL,
    source_kind text NOT NULL,
    recurrence_unit text NOT NULL,
    recurrence_interval integer NOT NULL,
    anchor_date date NOT NULL,
    start_date date NOT NULL,
    end_date date,
    status text NOT NULL,
    amount numeric(28,2) NOT NULL,
    total_expense numeric(28,2),
    business_use_percentage numeric(8,5),
    account_id text NOT NULL,
    category_id text NOT NULL,
    payee_id text,
    description text NOT NULL DEFAULT '',
    reference text NOT NULL DEFAULT '',
    allocation_rationale text NOT NULL DEFAULT '',
    attention_code text NOT NULL DEFAULT '',
    attention_at timestamptz,
    CONSTRAINT pk_recurring_schedules PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_recurring_schedules_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_recurring_schedules_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_recurring_schedules_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_recurring_schedules_version CHECK (version > 0),
    CONSTRAINT ck_recurring_schedules_amount_finite CHECK (amount <> 'NaN'::numeric),
    CONSTRAINT ck_recurring_schedules_total_expense_finite CHECK (total_expense <> 'NaN'::numeric),
    CONSTRAINT ck_recurring_schedules_business_use_percentage_finite CHECK (business_use_percentage <> 'NaN'::numeric),
    CONSTRAINT ck_recurring_schedules_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_recurring_schedules_source CHECK (source_kind IN ('transaction','mixed_use')),
    CONSTRAINT ck_recurring_schedules_unit CHECK (recurrence_unit IN ('day','week','month','year')),
    CONSTRAINT ck_recurring_schedules_interval CHECK (recurrence_interval > 0),
    CONSTRAINT ck_recurring_schedules_status CHECK (status IN ('active','paused','ended')),
    CONSTRAINT ck_recurring_schedules_amount CHECK (amount > 0),
    CONSTRAINT ck_recurring_schedules_dates CHECK (anchor_date = start_date AND (end_date IS NULL OR end_date >= start_date OR status = 'ended')),
    CONSTRAINT ck_recurring_schedules_template CHECK ((source_kind = 'transaction' AND total_expense IS NULL AND business_use_percentage IS NULL AND allocation_rationale = '') OR (source_kind = 'mixed_use' AND total_expense IS NOT NULL AND business_use_percentage IS NOT NULL AND total_expense > 0 AND business_use_percentage > 0 AND business_use_percentage <= 100 AND amount <= total_expense AND btrim(allocation_rationale) <> '')),
    CONSTRAINT fk_recurring_schedules_account_id FOREIGN KEY (entity_id, account_id) REFERENCES accounts (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_recurring_schedules_category_id FOREIGN KEY (entity_id, category_id) REFERENCES categories (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_recurring_schedules_payee_id FOREIGN KEY (entity_id, payee_id) REFERENCES payees (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_recurring_schedules_account_id ON recurring_schedules (entity_id, account_id);

CREATE INDEX ix_recurring_schedules_category_id ON recurring_schedules (entity_id, category_id);

CREATE INDEX ix_recurring_schedules_payee_id ON recurring_schedules (entity_id, payee_id);

CREATE INDEX ix_recurring_schedules_due ON recurring_schedules (entity_id, status, start_date, id);

CREATE TABLE schedule_tags (
    entity_id text NOT NULL,
    schedule_id text NOT NULL,
    tag_id text NOT NULL,
    CONSTRAINT pk_schedule_tags PRIMARY KEY (entity_id, schedule_id, tag_id),
    CONSTRAINT fk_schedule_tags_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT fk_schedule_tags_schedule_id FOREIGN KEY (entity_id, schedule_id) REFERENCES recurring_schedules (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_schedule_tags_tag_id FOREIGN KEY (entity_id, tag_id) REFERENCES tags (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_schedule_tags_schedule_id ON schedule_tags (entity_id, schedule_id);

CREATE INDEX ix_schedule_tags_tag_id ON schedule_tags (entity_id, tag_id);

CREATE INDEX ix_schedule_tags_reverse ON schedule_tags (entity_id, tag_id, schedule_id);

CREATE TABLE recurring_occurrences (
    entity_id text NOT NULL,
    schedule_id text NOT NULL,
    scheduled_date date NOT NULL,
    source_kind text NOT NULL,
    occurrence_type text NOT NULL,
    entry_id text,
    mixed_use_source_id text,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_recurring_occurrences PRIMARY KEY (entity_id, schedule_id, scheduled_date),
    CONSTRAINT fk_recurring_occurrences_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_recurring_occurrences_type CHECK (occurrence_type IN ('initial','generated')),
    CONSTRAINT ck_recurring_occurrences_target CHECK ((source_kind = 'transaction' AND entry_id IS NOT NULL AND mixed_use_source_id IS NULL) OR (source_kind = 'mixed_use' AND entry_id IS NULL AND mixed_use_source_id IS NOT NULL)),
    CONSTRAINT fk_recurring_occurrences_schedule_id FOREIGN KEY (entity_id, schedule_id) REFERENCES recurring_schedules (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_recurring_occurrences_entry_id FOREIGN KEY (entity_id, entry_id) REFERENCES entries (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_recurring_occurrences_mixed_use_source_id FOREIGN KEY (entity_id, mixed_use_source_id) REFERENCES mixed_use_sources (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_recurring_occurrences_entry_id UNIQUE (entity_id, entry_id),
    CONSTRAINT uq_recurring_occurrences_mixed_use_source_id UNIQUE (entity_id, mixed_use_source_id)
);

CREATE INDEX ix_recurring_occurrences_schedule_id ON recurring_occurrences (entity_id, schedule_id);

CREATE INDEX ix_recurring_occurrences_entry_id ON recurring_occurrences (entity_id, entry_id);

CREATE INDEX ix_recurring_occurrences_mixed_use_source_id ON recurring_occurrences (entity_id, mixed_use_source_id);

CREATE INDEX ix_recurring_occurrences_date ON recurring_occurrences (entity_id, scheduled_date, schedule_id);

CREATE TABLE fixed_assets (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    name text NOT NULL,
    asset_type text NOT NULL,
    notes text NOT NULL DEFAULT '',
    acquisition_date date NOT NULL,
    depreciation_start_date date NOT NULL,
    cost_basis numeric(28,2) NOT NULL,
    salvage_value numeric(28,2) NOT NULL,
    useful_life_quarters integer NOT NULL,
    depreciation_method text NOT NULL,
    expense_category_id text,
    accumulated_depreciation_account_id text,
    payee_id text,
    reference text NOT NULL DEFAULT '',
    source_entry_id text,
    retired_date date,
    status text NOT NULL,
    CONSTRAINT pk_fixed_assets PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_fixed_assets_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_fixed_assets_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_fixed_assets_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_fixed_assets_version CHECK (version > 0),
    CONSTRAINT ck_fixed_assets_cost_basis_finite CHECK (cost_basis <> 'NaN'::numeric),
    CONSTRAINT ck_fixed_assets_salvage_value_finite CHECK (salvage_value <> 'NaN'::numeric),
    CONSTRAINT ck_fixed_assets_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_fixed_assets_type CHECK (asset_type IN ('Computers & office equipment','Furniture, fixtures & appliances','Photography, communication & video equipment','Machinery, equipment & tools','Vehicles','Construction equipment','Farm equipment','Residential rental property','Commercial real property','Land improvements','Leasehold improvements','Software & other intangibles','Other depreciable property')),
    CONSTRAINT ck_fixed_assets_method CHECK (depreciation_method = 'Straight-line'),
    CONSTRAINT ck_fixed_assets_basis CHECK (cost_basis > 0 AND salvage_value >= 0 AND salvage_value < cost_basis),
    CONSTRAINT ck_fixed_assets_life CHECK (useful_life_quarters > 0),
    CONSTRAINT ck_fixed_assets_dates CHECK (depreciation_start_date >= acquisition_date AND (retired_date IS NULL OR retired_date >= acquisition_date)),
    CONSTRAINT ck_fixed_assets_status CHECK ((status = 'active' AND retired_date IS NULL) OR (status = 'retired' AND retired_date IS NOT NULL)),
    CONSTRAINT fk_fixed_assets_expense_category_id FOREIGN KEY (entity_id, expense_category_id) REFERENCES categories (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_fixed_assets_accumulated_depreciation_account_id FOREIGN KEY (entity_id, accumulated_depreciation_account_id) REFERENCES accounts (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_fixed_assets_payee_id FOREIGN KEY (entity_id, payee_id) REFERENCES payees (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_fixed_assets_source_entry_id FOREIGN KEY (entity_id, source_entry_id) REFERENCES entries (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_fixed_assets_expense_category_id ON fixed_assets (entity_id, expense_category_id);

CREATE INDEX ix_fixed_assets_accumulated_depreciation_account_id ON fixed_assets (entity_id, accumulated_depreciation_account_id);

CREATE INDEX ix_fixed_assets_payee_id ON fixed_assets (entity_id, payee_id);

CREATE INDEX ix_fixed_assets_source_entry_id ON fixed_assets (entity_id, source_entry_id);

CREATE INDEX ix_fixed_assets_status_date ON fixed_assets (entity_id, status, acquisition_date, id);

CREATE TABLE asset_tags (
    entity_id text NOT NULL,
    asset_id text NOT NULL,
    tag_id text NOT NULL,
    CONSTRAINT pk_asset_tags PRIMARY KEY (entity_id, asset_id, tag_id),
    CONSTRAINT fk_asset_tags_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT fk_asset_tags_asset_id FOREIGN KEY (entity_id, asset_id) REFERENCES fixed_assets (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_asset_tags_tag_id FOREIGN KEY (entity_id, tag_id) REFERENCES tags (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_asset_tags_asset_id ON asset_tags (entity_id, asset_id);

CREATE INDEX ix_asset_tags_tag_id ON asset_tags (entity_id, tag_id);

CREATE INDEX ix_asset_tags_reverse ON asset_tags (entity_id, tag_id, asset_id);

ALTER TABLE entries ADD CONSTRAINT fk_entries_depreciation_asset FOREIGN KEY (entity_id,depreciation_asset_id) REFERENCES fixed_assets(entity_id,id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE asset_period_overrides (
    entity_id text NOT NULL,
    asset_id text NOT NULL,
    sequence integer NOT NULL,
    amount numeric(28,2) NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_asset_period_overrides PRIMARY KEY (entity_id, asset_id, sequence),
    CONSTRAINT fk_asset_period_overrides_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_asset_period_overrides_amount_finite CHECK (amount <> 'NaN'::numeric),
    CONSTRAINT ck_asset_period_overrides_reason CHECK (btrim(reason) <> ''),
    CONSTRAINT ck_asset_period_overrides_sequence CHECK (sequence > 0),
    CONSTRAINT ck_asset_period_overrides_amount CHECK (amount >= 0),
    CONSTRAINT fk_asset_period_overrides_asset_id FOREIGN KEY (entity_id, asset_id) REFERENCES fixed_assets (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_asset_period_overrides_asset_id ON asset_period_overrides (entity_id, asset_id);

CREATE TABLE depreciation_events (
    entity_id text NOT NULL,
    asset_id text NOT NULL,
    sequence integer NOT NULL,
    entry_id text NOT NULL,
    scheduled_date date NOT NULL,
    amount numeric(28,2) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_depreciation_events PRIMARY KEY (entity_id, asset_id, sequence),
    CONSTRAINT fk_depreciation_events_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_depreciation_events_amount_finite CHECK (amount <> 'NaN'::numeric),
    CONSTRAINT ck_depreciation_events_sequence CHECK (sequence > 0),
    CONSTRAINT ck_depreciation_events_amount CHECK (amount >= 0),
    CONSTRAINT fk_depreciation_events_asset_id FOREIGN KEY (entity_id, asset_id) REFERENCES fixed_assets (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_depreciation_events_entry_id FOREIGN KEY (entity_id, entry_id) REFERENCES entries (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_depreciation_events_entry_id UNIQUE (entity_id, entry_id)
);

CREATE INDEX ix_depreciation_events_asset_id ON depreciation_events (entity_id, asset_id);

CREATE INDEX ix_depreciation_events_entry_id ON depreciation_events (entity_id, entry_id);

CREATE INDEX ix_depreciation_events_date ON depreciation_events (entity_id, scheduled_date, asset_id);

CREATE TABLE mileage_records (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    trip_date date NOT NULL,
    miles numeric(28,1) NOT NULL,
    vehicle text NOT NULL DEFAULT '',
    start_location text NOT NULL,
    destination text NOT NULL,
    business_purpose text NOT NULL,
    notes text NOT NULL DEFAULT '',
    CONSTRAINT pk_mileage_records PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_mileage_records_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_mileage_records_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_mileage_records_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_mileage_records_version CHECK (version > 0),
    CONSTRAINT ck_mileage_records_miles_finite CHECK (miles <> 'NaN'::numeric),
    CONSTRAINT ck_mileage_records_start_location CHECK (btrim(start_location) <> ''),
    CONSTRAINT ck_mileage_records_destination CHECK (btrim(destination) <> ''),
    CONSTRAINT ck_mileage_records_business_purpose CHECK (btrim(business_purpose) <> ''),
    CONSTRAINT ck_mileage_records_miles CHECK (miles > 0)
);

CREATE INDEX ix_mileage_records_date ON mileage_records (entity_id, trip_date, id);

CREATE TABLE mileage_tags (
    entity_id text NOT NULL,
    mileage_id text NOT NULL,
    tag_id text NOT NULL,
    CONSTRAINT pk_mileage_tags PRIMARY KEY (entity_id, mileage_id, tag_id),
    CONSTRAINT fk_mileage_tags_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT fk_mileage_tags_mileage_id FOREIGN KEY (entity_id, mileage_id) REFERENCES mileage_records (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_mileage_tags_tag_id FOREIGN KEY (entity_id, tag_id) REFERENCES tags (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_mileage_tags_mileage_id ON mileage_tags (entity_id, mileage_id);

CREATE INDEX ix_mileage_tags_tag_id ON mileage_tags (entity_id, tag_id);

CREATE INDEX ix_mileage_tags_reverse ON mileage_tags (entity_id, tag_id, mileage_id);

CREATE TABLE documents (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    stored_filename text NOT NULL,
    original_filename text NOT NULL DEFAULT '',
    mime_type text NOT NULL DEFAULT '',
    byte_size bigint,
    sha256 text,
    store_kind text NOT NULL,
    store_scope_key text NOT NULL DEFAULT '',
    storage_key text NOT NULL,
    open_url text NOT NULL DEFAULT '',
    CONSTRAINT pk_documents PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_documents_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_documents_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_documents_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_documents_version CHECK (version > 0),
    CONSTRAINT ck_documents_stored_filename CHECK (btrim(stored_filename) <> ''),
    CONSTRAINT ck_documents_store_kind CHECK (btrim(store_kind) <> ''),
    CONSTRAINT ck_documents_storage_key CHECK (btrim(storage_key) <> ''),
    CONSTRAINT ck_documents_size CHECK (byte_size >= 0),
    CONSTRAINT ck_documents_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_documents_store_kind_store_scope_key_storage_key UNIQUE (entity_id, store_kind, store_scope_key, storage_key)
);

CREATE TABLE document_links (
    entity_id text NOT NULL,
    document_id text NOT NULL,
    entry_id text,
    mixed_use_source_id text,
    position integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_document_links PRIMARY KEY (entity_id, document_id),
    CONSTRAINT fk_document_links_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_document_links_target CHECK (num_nonnulls(entry_id,mixed_use_source_id) = 1),
    CONSTRAINT ck_document_links_position CHECK (position > 0),
    CONSTRAINT fk_document_links_document_id FOREIGN KEY (entity_id, document_id) REFERENCES documents (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_document_links_entry_id FOREIGN KEY (entity_id, entry_id) REFERENCES entries (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_document_links_mixed_use_source_id FOREIGN KEY (entity_id, mixed_use_source_id) REFERENCES mixed_use_sources (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_document_links_document_id ON document_links (entity_id, document_id);

CREATE INDEX ix_document_links_entry_id ON document_links (entity_id, entry_id);

CREATE INDEX ix_document_links_mixed_use_source_id ON document_links (entity_id, mixed_use_source_id);

CREATE UNIQUE INDEX uq_document_links_entry_id_position ON document_links(entity_id,entry_id,position) WHERE entry_id IS NOT NULL;

CREATE UNIQUE INDEX uq_document_links_mixed_use_source_id_position ON document_links(entity_id,mixed_use_source_id,position) WHERE mixed_use_source_id IS NOT NULL;

CREATE TABLE import_batches (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    source_kind text NOT NULL,
    format_version text NOT NULL,
    status text NOT NULL,
    CONSTRAINT pk_import_batches PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_import_batches_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_import_batches_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_import_batches_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_import_batches_version CHECK (version > 0),
    CONSTRAINT ck_import_batches_format_version CHECK (btrim(format_version) <> ''),
    CONSTRAINT ck_import_batches_source CHECK (source_kind IN ('csv','quickbooks')),
    CONSTRAINT ck_import_batches_status CHECK (status IN ('prepared','complete','failed'))
);

CREATE TABLE import_records (
    entity_id text NOT NULL,
    batch_id text NOT NULL,
    source_position integer NOT NULL,
    record_kind text NOT NULL,
    entry_id text,
    mileage_id text,
    fingerprint text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_import_records PRIMARY KEY (entity_id, batch_id, source_position),
    CONSTRAINT fk_import_records_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_import_records_fingerprint CHECK (btrim(fingerprint) <> ''),
    CONSTRAINT ck_import_records_position CHECK (source_position > 0),
    CONSTRAINT ck_import_records_target CHECK ((record_kind = 'entry' AND entry_id IS NOT NULL AND mileage_id IS NULL) OR (record_kind = 'mileage' AND entry_id IS NULL AND mileage_id IS NOT NULL)),
    CONSTRAINT fk_import_records_batch_id FOREIGN KEY (entity_id, batch_id) REFERENCES import_batches (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_import_records_entry_id FOREIGN KEY (entity_id, entry_id) REFERENCES entries (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_import_records_mileage_id FOREIGN KEY (entity_id, mileage_id) REFERENCES mileage_records (entity_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_import_records_batch_id ON import_records (entity_id, batch_id);

CREATE INDEX ix_import_records_entry_id ON import_records (entity_id, entry_id);

CREATE INDEX ix_import_records_mileage_id ON import_records (entity_id, mileage_id);

CREATE INDEX ix_import_records_fingerprint ON import_records (entity_id, fingerprint);

CREATE TABLE migration_runs (
    entity_id text NOT NULL,
    id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    incarnation_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    source_profile_key text NOT NULL,
    source_workbook_key text NOT NULL,
    source_kind text NOT NULL,
    source_backup_version smallint,
    manifest_version text NOT NULL,
    mapping_version text NOT NULL,
    source_snapshot_sha256 text NOT NULL,
    extracted_at timestamptz NOT NULL,
    status text NOT NULL,
    CONSTRAINT pk_migration_runs PRIMARY KEY (entity_id, id),
    CONSTRAINT fk_migration_runs_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_migration_runs_id CHECK (btrim(id) <> ''),
    CONSTRAINT ck_migration_runs_incarnation_id CHECK (btrim(incarnation_id) <> ''),
    CONSTRAINT ck_migration_runs_version CHECK (version > 0),
    CONSTRAINT ck_migration_runs_source_profile_key CHECK (btrim(source_profile_key) <> ''),
    CONSTRAINT ck_migration_runs_source_workbook_key CHECK (btrim(source_workbook_key) <> ''),
    CONSTRAINT ck_migration_runs_manifest_version CHECK (btrim(manifest_version) <> ''),
    CONSTRAINT ck_migration_runs_mapping_version CHECK (btrim(mapping_version) <> ''),
    CONSTRAINT ck_migration_runs_source CHECK ((source_kind = 'current_workbook' AND source_backup_version IS NULL) OR (source_kind = 'v13_backup' AND source_backup_version IS NOT NULL AND source_backup_version = 13)),
    CONSTRAINT ck_migration_runs_digest CHECK (source_snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_migration_runs_status CHECK (status IN ('prepared','loading','failed','validated'))
);

CREATE INDEX ix_migration_runs_snapshot ON migration_runs (entity_id, source_snapshot_sha256, id);

CREATE TABLE migration_units (
    entity_id text NOT NULL,
    run_id text NOT NULL,
    unit_key text NOT NULL,
    unit_kind text NOT NULL,
    unit_sha256 text NOT NULL,
    status text NOT NULL,
    loaded_at timestamptz,
    CONSTRAINT pk_migration_units PRIMARY KEY (entity_id, run_id, unit_key),
    CONSTRAINT fk_migration_units_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_migration_units_unit_key CHECK (btrim(unit_key) <> ''),
    CONSTRAINT ck_migration_units_unit_kind CHECK (btrim(unit_kind) <> ''),
    CONSTRAINT ck_migration_units_digest CHECK (unit_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_migration_units_status CHECK (status IN ('pending','loaded','failed')),
    CONSTRAINT ck_migration_units_loaded CHECK ((status = 'loaded') = (loaded_at IS NOT NULL)),
    CONSTRAINT fk_migration_units_run_id FOREIGN KEY (entity_id, run_id) REFERENCES migration_runs (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_migration_units_run_id ON migration_units (entity_id, run_id);

CREATE TABLE migration_id_mappings (
    entity_id text NOT NULL,
    run_id text NOT NULL,
    source_record_kind text NOT NULL,
    source_id text NOT NULL,
    target_record_kind text NOT NULL,
    target_id text NOT NULL,
    mapping_reason text NOT NULL,
    CONSTRAINT pk_migration_id_mappings PRIMARY KEY (entity_id, run_id, source_record_kind, source_id),
    CONSTRAINT fk_migration_id_mappings_entity FOREIGN KEY (entity_id) REFERENCES business_entities(id),
    CONSTRAINT ck_migration_id_mappings_source_record_kind CHECK (btrim(source_record_kind) <> ''),
    CONSTRAINT ck_migration_id_mappings_source_id CHECK (btrim(source_id) <> ''),
    CONSTRAINT ck_migration_id_mappings_target_record_kind CHECK (btrim(target_record_kind) <> ''),
    CONSTRAINT ck_migration_id_mappings_target_id CHECK (btrim(target_id) <> ''),
    CONSTRAINT ck_migration_id_mappings_mapping_reason CHECK (btrim(mapping_reason) <> ''),
    CONSTRAINT fk_migration_id_mappings_run_id FOREIGN KEY (entity_id, run_id) REFERENCES migration_runs (entity_id, id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT uq_migration_id_mappings_run_id_target_record_kind_target_id UNIQUE (entity_id, run_id, target_record_kind, target_id)
);

CREATE INDEX ix_migration_id_mappings_run_id ON migration_id_mappings (entity_id, run_id);

CREATE INDEX ix_migration_id_mappings_target ON migration_id_mappings (entity_id, target_record_kind, target_id);
