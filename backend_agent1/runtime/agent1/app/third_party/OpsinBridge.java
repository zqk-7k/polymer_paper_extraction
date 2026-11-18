// Adapter source only. OPSIN is a separately installed MIT-licensed dependency.
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import uk.ac.cam.ch.wwmm.opsin.*;
public final class OpsinBridge {
  static String b64(String s) { return Base64.getEncoder().encodeToString((s == null ? "" : s).getBytes(StandardCharsets.UTF_8)); }
  public static void main(String[] args) throws Exception {
    NameToStructure nts = NameToStructure.getInstance();
    NameToStructureConfig config = new NameToStructureConfig();
    // Default strict behavior: no silently ignored stereochemistry or radicals.
    if (args.length == 1 && args[0].equals("--allow-radicals")) config.setAllowRadicals(true);
    BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    PrintWriter out = new PrintWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8), true);
    String line;
    while ((line = in.readLine()) != null) {
      try {
        String name = new String(Base64.getDecoder().decode(line), StandardCharsets.UTF_8);
        if (name.length() > 5000) { out.println("LIMIT\t\t"+b64("Name length limit")); continue; }
        OpsinResult r = nts.parseChemicalName(name, config);
        out.println(r.getStatus().toString()+"\t"+b64(r.getSmiles())+"\t"+b64(r.getMessage()));
      } catch (Exception ex) { out.println("ERROR\t\t"+b64(ex.getClass().getSimpleName()+": "+ex.getMessage())); }
    }
  }
}
