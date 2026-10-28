package lab.demo;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Holds byte arrays on the heap so you can watch
 * jvm_memory_used_bytes climb in Prometheus.
 * The process heap ceiling is 256 MiB, set in the Dockerfile.
 */
@RestController
public class MemoryController {

  private final List<byte[]> held = new ArrayList<>();

  @PostMapping("/memory/hold")
  public Map<String, Object> hold(@RequestParam(defaultValue = "32") int megabytes) {
    if (megabytes < 1 || megabytes > 64) {
      throw new IllegalArgumentException("megabytes must be between 1 and 64");
    }
    held.add(new byte[megabytes * 1024 * 1024]);
    return status();
  }

  @PostMapping("/memory/release")
  public Map<String, Object> release() {
    held.clear();
    return status();
  }

  private Map<String, Object> status() {
    Runtime runtime = Runtime.getRuntime();
    long used = runtime.totalMemory() - runtime.freeMemory();
    return Map.of(
        "chunks", held.size(),
        "usedBytes", used,
        "maxBytes", runtime.maxMemory());
  }
}
