# Builder stage: compiles and packages the application.
FROM eclipse-temurin:21-jdk AS builder
WORKDIR /build

COPY mvnw pom.xml ./
COPY .mvn/ .mvn/
RUN ./mvnw -B dependency:go-offline

COPY src/ src/
RUN ./mvnw -B package

# Runtime stage: only the built JAR, no build tooling.
FROM eclipse-temurin:21-jre AS runtime

# Pinned OpenTelemetry Java agent (2.31.1, official release artifact),
# fetched via ADD so no curl/wget is needed in the image, with a pinned
# sha256 for integrity. Present at a fixed path but NOT referenced by
# ENTRYPOINT below, so this image still runs with no telemetry when
# launched standalone; Docker Compose attaches it (only for
# checkout-service, only in this environment) via
# JAVA_TOOL_OPTIONS=-javaagent:/opt/opentelemetry-javaagent.jar.
ADD --chmod=644 --checksum=sha256:bbf83c151b6400709e2f225bdd07a04f839d9d13b8b93464241333fd25d3e3ba \
    https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v2.31.1/opentelemetry-javaagent.jar \
    /opt/opentelemetry-javaagent.jar

RUN groupadd --system app && useradd --system --gid app --no-create-home app
USER app

WORKDIR /app
COPY --from=builder /build/target/checkout-service-*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
