"""Static catalog of the fictional company the demo runs on.

Services are listed in dependency order: a service may only depend on services
that appear *later* in SERVICES. That keeps DEPENDS_ON a DAG by construction.
"""

TEAMS = [
    # slug, name, domain
    ("edge", "Edge & Gateway", "edge"),
    ("checkout", "Checkout", "commerce"),
    ("catalog", "Catalog & Search", "commerce"),
    ("identity", "Identity", "platform"),
    ("fulfillment", "Fulfillment", "commerce"),
    ("growth", "Growth", "engagement"),
    ("platform", "Platform", "platform"),
    ("data", "Data", "data"),
]

PEOPLE = [
    # handle, name, role, team
    ("maya", "Maya Rao", "Staff Engineer", "edge"),
    ("leo", "Leo Martins", "SRE", "edge"),
    ("aisha", "Aisha Khan", "Senior Engineer", "checkout"),
    ("tom", "Tom Becker", "Engineer", "checkout"),
    ("nina", "Nina Petrova", "Engineering Manager", "checkout"),
    ("raj", "Raj Iyer", "Senior Engineer", "catalog"),
    ("sofia", "Sofia Lopez", "Engineer", "catalog"),
    ("kenji", "Kenji Sato", "Security Engineer", "identity"),
    ("emma", "Emma Wilson", "Engineer", "identity"),
    ("omar", "Omar Haddad", "Senior Engineer", "fulfillment"),
    ("lin", "Lin Chen", "Engineer", "fulfillment"),
    ("zoe", "Zoe Adams", "Engineer", "growth"),
    ("arjun", "Arjun Mehta", "Senior Engineer", "growth"),
    ("priya", "Priya Nair", "Platform Engineer", "platform"),
    ("dan", "Dan Novak", "SRE", "platform"),
    ("eva", "Eva Fischer", "Staff Engineer", "platform"),
    ("sam", "Sam Okoro", "Data Engineer", "data"),
    ("ines", "Ines Duarte", "Data Engineer", "data"),
]

# The person on call for each team (wide window so the demo never "expires").
ON_CALL = {
    "edge": "leo",
    "checkout": "aisha",
    "catalog": "raj",
    "identity": "kenji",
    "fulfillment": "omar",
    "growth": "zoe",
    "platform": "priya",
    "data": "sam",
}

# name, team, tier, layer, language, hand-picked dependencies
SERVICES = [
    # Edge
    ("cdn-edge", "edge", "critical", "edge", "go", ["api-gateway"]),
    ("api-gateway", "edge", "critical", "edge", "go", ["web-bff", "mobile-bff", "rate-limiter", "auth-service"]),
    ("web-bff", "edge", "critical", "edge", "typescript",
     ["checkout-api", "cart-service", "catalog-service", "search-service", "user-profile", "recommendations"]),
    ("mobile-bff", "edge", "high", "edge", "typescript",
     ["checkout-api", "cart-service", "catalog-service", "search-service", "user-profile", "notifications"]),
    # Business
    ("checkout-api", "checkout", "critical", "business", "java",
     ["cart-service", "payments-api", "orders-service", "inventory-service", "pricing-service", "tax-service"]),
    ("cart-service", "checkout", "critical", "business", "java",
     ["inventory-service", "pricing-service", "promotions", "redis-cache"]),
    ("payments-api", "checkout", "critical", "business", "java", ["fraud-detector", "secrets-vault", "kafka-bus"]),
    ("orders-service", "fulfillment", "critical", "business", "go",
     ["inventory-service", "shipping-service", "kafka-bus", "inventory-db-proxy"]),
    ("loyalty-service", "growth", "medium", "business", "python", ["user-profile", "kafka-bus"]),
    ("promotions", "growth", "medium", "business", "python", ["pricing-service", "feature-flags"]),
    ("recommendations", "growth", "medium", "business", "python",
     ["catalog-service", "ml-feature-store", "redis-cache"]),
    ("reviews-service", "catalog", "low", "business", "python", ["catalog-service", "user-profile"]),
    ("search-service", "catalog", "high", "business", "go", ["catalog-service", "redis-cache"]),
    ("catalog-service", "catalog", "high", "business", "go", ["pricing-service", "inventory-service"]),
    ("shipping-service", "fulfillment", "high", "business", "go", ["notifications", "inventory-service"]),
    ("inventory-service", "fulfillment", "critical", "business", "go", ["inventory-db-proxy", "kafka-bus"]),
    ("pricing-service", "catalog", "high", "business", "java", ["tax-service", "redis-cache", "feature-flags"]),
    ("tax-service", "checkout", "high", "business", "java", ["config-service"]),
    ("fraud-detector", "checkout", "critical", "business", "python", ["ml-feature-store", "user-profile"]),
    ("notifications", "growth", "medium", "business", "typescript", ["email-sender", "sms-sender", "kafka-bus"]),
    ("email-sender", "growth", "low", "business", "typescript", ["secrets-vault"]),
    ("sms-sender", "growth", "low", "business", "typescript", ["secrets-vault"]),
    ("user-profile", "identity", "high", "business", "java", ["auth-service", "redis-cache", "feature-flags"]),
    ("auth-service", "identity", "critical", "business", "go", ["feature-flags", "secrets-vault", "session-store"]),
    ("session-store", "identity", "critical", "business", "go", ["redis-cache"]),
    # Data
    ("ml-feature-store", "data", "medium", "data", "python", ["redis-cache", "analytics-ingest"]),
    ("etl-scheduler", "data", "low", "data", "python", ["analytics-ingest", "secrets-vault"]),
    ("analytics-ingest", "data", "low", "data", "python", ["kafka-bus"]),
    ("metrics-collector", "data", "medium", "data", "go", ["kafka-bus"]),
    ("logging-pipeline", "data", "medium", "data", "go", ["kafka-bus"]),
    # Platform chokepoints
    ("inventory-db-proxy", "platform", "critical", "platform", "go", ["service-mesh", "secrets-vault"]),
    ("redis-cache", "platform", "critical", "platform", "c", ["service-mesh"]),
    ("feature-flags", "platform", "high", "platform", "go", ["config-service"]),
    ("rate-limiter", "platform", "high", "platform", "go", ["service-mesh"]),
    ("kafka-bus", "platform", "critical", "platform", "java", ["service-mesh"]),
    ("config-service", "platform", "high", "platform", "go", ["secrets-vault", "service-mesh"]),
    ("secrets-vault", "platform", "critical", "platform", "go", ["service-mesh"]),
    ("service-mesh", "platform", "critical", "platform", "go", []),
]

DATABASES = [
    # name, engine, size_gb, owner team
    ("inventory-db", "postgres", 420, "fulfillment"),
    ("orders-db", "postgres", 860, "fulfillment"),
    ("payments-db", "postgres", 310, "checkout"),
    ("users-db", "postgres", 150, "identity"),
    ("catalog-db", "postgres", 95, "catalog"),
    ("search-index", "elasticsearch", 240, "catalog"),
    ("events-warehouse", "clickhouse", 2100, "data"),
    ("feature-store-db", "cassandra", 380, "data"),
]

# service, database, READS_FROM | WRITES_TO
DATA_ACCESS = [
    ("inventory-db-proxy", "inventory-db", "WRITES_TO"),
    ("inventory-db-proxy", "inventory-db", "READS_FROM"),
    ("orders-service", "orders-db", "WRITES_TO"),
    ("payments-api", "payments-db", "WRITES_TO"),
    ("user-profile", "users-db", "READS_FROM"),
    ("auth-service", "users-db", "READS_FROM"),
    ("catalog-service", "catalog-db", "READS_FROM"),
    ("search-service", "search-index", "READS_FROM"),
    ("analytics-ingest", "events-warehouse", "WRITES_TO"),
    ("etl-scheduler", "events-warehouse", "READS_FROM"),
    ("ml-feature-store", "feature-store-db", "READS_FROM"),
    ("ml-feature-store", "feature-store-db", "WRITES_TO"),
]

# Every service also talks to the observability pipeline; those edges are added by the generator
# for business services only, to keep the picture readable.
OBSERVABILITY = ["metrics-collector", "logging-pipeline"]

# Revenue that depends on each user-facing service, in $/minute (drives the cost-of-downtime ticker).
REVENUE_PER_MIN = {
    "checkout-api": 1800, "payments-api": 1500, "cart-service": 700, "orders-service": 900,
    "web-bff": 1200, "mobile-bff": 800, "api-gateway": 2400, "cdn-edge": 2600,
    "search-service": 450, "catalog-service": 500, "recommendations": 300, "pricing-service": 350,
    "inventory-service": 600, "auth-service": 1100, "user-profile": 250, "session-store": 400,
    "promotions": 150, "loyalty-service": 80, "notifications": 120, "shipping-service": 200,
    "fraud-detector": 650, "tax-service": 300, "reviews-service": 40,
}

# Plausible commit messages for chaos-mode deploys.
CHAOS_CHANGES = [
    "Lower connection timeout from 5s to 500ms",
    "Switch serializer to the new protobuf schema",
    "Enable aggressive retry with no backoff",
    "Halve worker pool to save memory",
    "Upgrade client library to 4.0 (breaking defaults)",
    "Turn on request-level debug logging",
]
