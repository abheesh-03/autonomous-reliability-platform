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

RUN groupadd --system app && useradd --system --gid app --no-create-home app
USER app

WORKDIR /app
COPY --from=builder /build/target/checkout-service-*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
