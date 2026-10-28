FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /src
COPY pom.xml .
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /src/target/demo-0.0.1.jar app.jar
EXPOSE 8080
# Fixed heap so "used" and "max" are easy to compare in Prometheus.
ENTRYPOINT ["java", "-Xms64m", "-Xmx256m", "-jar", "app.jar"]
