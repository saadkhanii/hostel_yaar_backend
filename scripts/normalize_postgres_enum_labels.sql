DO $$
DECLARE
    enum_change record;
    old_label_exists boolean;
    new_label_exists boolean;
BEGIN
    FOR enum_change IN
        SELECT *
        FROM (VALUES
            ('hosteltype', 'boys', 'Boys'),
            ('hosteltype', 'girls', 'Girls'),
            ('hosteltype', 'mixed', 'Mixed'),
            ('bookingtype', 'room', 'Room'),
            ('bookingtype', 'seat', 'Seat')
        ) AS labels(type_name, old_label, new_label)
    LOOP
        IF to_regtype(enum_change.type_name) IS NULL THEN
            RAISE EXCEPTION 'PostgreSQL enum type % does not exist', enum_change.type_name;
        END IF;

        SELECT EXISTS (
            SELECT 1
            FROM pg_enum
            WHERE enumtypid = to_regtype(enum_change.type_name)
              AND enumlabel = enum_change.old_label
        ) INTO old_label_exists;

        SELECT EXISTS (
            SELECT 1
            FROM pg_enum
            WHERE enumtypid = to_regtype(enum_change.type_name)
              AND enumlabel = enum_change.new_label
        ) INTO new_label_exists;

        IF old_label_exists AND new_label_exists THEN
            RAISE EXCEPTION 'Enum % contains both labels % and %; resolve duplicate labels before running this script',
                enum_change.type_name, enum_change.old_label, enum_change.new_label;
        ELSIF old_label_exists THEN
            EXECUTE format(
                'ALTER TYPE %I RENAME VALUE %L TO %L',
                enum_change.type_name,
                enum_change.old_label,
                enum_change.new_label
            );
        END IF;
    END LOOP;
END $$;