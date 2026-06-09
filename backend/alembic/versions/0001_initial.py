"""Initial migration with TimescaleDB hypertable, PostGIS, and continuous aggregate

Revision ID: 0001_initial
Revises: 
Create Date: 2026-06-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable PostGIS extension for spatial data types
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis SCHEMA public")
    
    # Enable TimescaleDB extension for time-series hypertables
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb SCHEMA public")
    
    # Create users table
    op.create_table(
        'users',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('hashed_password', sa.Text(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('user_id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=False)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=False)
    
    # Create trips table
    op.create_table(
        'trips',
        sa.Column('trip_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('trip_name', sa.String(length=255), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('min_lat', sa.DoublePrecision(), nullable=False),
        sa.Column('max_lat', sa.DoublePrecision(), nullable=False),
        sa.Column('min_lon', sa.DoublePrecision(), nullable=False),
        sa.Column('max_lon', sa.DoublePrecision(), nullable=False),
        sa.Column('total_distance_meters', sa.DoublePrecision(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('trip_id'),
        sa.CheckConstraint('end_time >= start_time', name='time_range_check')
    )
    op.create_index('ix_trips_user_time', 'trips', ['user_id', 'start_time'], unique=False)
    op.create_index(op.f('ix_trips_user_id'), 'trips', ['user_id'], unique=False)
    op.create_index(op.f('ix_trips_start_time'), 'trips', ['start_time'], unique=False)
    
    # Create telemetry_points table
    op.create_table(
        'telemetry_points',
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('trip_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('geom', sa.Text(), nullable=False),
        sa.Column('speed', sa.DoublePrecision(), nullable=False),
        sa.Column('voltage', sa.DoublePrecision(), nullable=True),
        sa.Column('current', sa.DoublePrecision(), nullable=True),
        sa.Column('power', sa.DoublePrecision(), nullable=True),
        sa.Column('torque', sa.DoublePrecision(), nullable=True),
        sa.Column('pwm', sa.Integer(), nullable=True),
        sa.Column('battery_level', sa.DoublePrecision(), nullable=True),
        sa.Column('distance', sa.DoublePrecision(), nullable=True),
        sa.Column('system_temp', sa.DoublePrecision(), nullable=True),
        sa.Column('temp2', sa.DoublePrecision(), nullable=True),
        sa.Column('tilt', sa.DoublePrecision(), nullable=True),
        sa.Column('roll', sa.DoublePrecision(), nullable=True),
        sa.Column('mode', sa.String(length=20), nullable=True),
        sa.Column('alert', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.trip_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('timestamp', 'trip_id')
    )
    
    # Create GIST index for spatial queries on geom column
    # Note: We use ST_GeomFromText to convert the text geometry to PostGIS geometry type
    op.execute("""
        CREATE INDEX idx_telemetry_spatial ON telemetry_points 
        USING GIST (ST_GeomFromText(geom, 4326))
    """)
    
    # Create index for playback: Locate trip points in chronological order
    op.execute("""
        CREATE INDEX idx_telemetry_playback ON telemetry_points 
        (trip_id, timestamp ASC)
    """)
    
    # Transform telemetry_points into a TimescaleDB hypertable
    # Chunking by 1 day is optimal for trips spanning a few hours
    op.execute("""
        SELECT create_hypertable('telemetry_points', 'timestamp', 
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => true)
    """)
    
    # Create continuous aggregate (downsampling)
    # Aggregates data into 1-minute buckets for fast charting
    op.execute("""
        CREATE MATERIALIZED VIEW telemetry_downsampled_1m
        WITH (timescaledb.continuous = true) AS
        SELECT 
            time_bucket('1 minute', timestamp) AS bucket,
            trip_id,
            avg(speed) as avg_speed,
            avg(voltage) as avg_voltage,
            avg(current) as avg_current,
            avg(battery_level) as avg_battery,
            max(system_temp) as max_temp
        FROM telemetry_points
        GROUP BY bucket, trip_id
    """)
    
    # Add refresh policy: Automatically update view when new data arrives
    op.execute("""
        SELECT add_continuous_aggregate_policy('telemetry_downsampled_1m',
            start_offset => INTERVAL '1 month',
            end_offset => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute',
            if_not_exists => true)
    """)
    
    # Enable compression on telemetry_points table
    op.execute("""
        ALTER TABLE telemetry_points SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'trip_id'
        )
    """)
    
    # Add compression policy: Compress telemetry data older than 7 days
    op.execute("""
        SELECT add_compression_policy('telemetry_points', INTERVAL '7 days',
            if_not_exists => true)
    """)


def downgrade() -> None:
    # Drop continuous aggregate policy
    op.execute("SELECT remove_continuous_aggregate_policy('telemetry_downsampled_1m', if_not_exists => true)")
    
    # Drop continuous aggregate
    op.execute("DROP MATERIALIZED VIEW IF EXISTS telemetry_downsampled_1m")
    
    # Drop hypertable (this will drop the underlying table)
    op.execute("SELECT drop_chunks('telemetry_points', INTERVAL '0 days', if_exists => true)")
    op.execute("SELECT drop_hypertable('telemetry_points', if_exists => true)")
    
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_telemetry_playback")
    op.execute("DROP INDEX IF EXISTS idx_telemetry_spatial")
    
    # Drop tables
    op.execute("DROP TABLE IF EXISTS telemetry_points")
    op.execute("DROP TABLE IF EXISTS trips")
    op.execute("DROP TABLE IF EXISTS users")
    
    # Disable extensions (optional - usually kept enabled)
    op.execute("DROP EXTENSION IF EXISTS timescaledb")
    op.execute("DROP EXTENSION IF EXISTS postgis")