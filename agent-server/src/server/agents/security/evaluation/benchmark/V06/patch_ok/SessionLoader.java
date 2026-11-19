import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.*;

public class SessionLoader {
    public Session load(InputStream in) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        return mapper.readValue(in, Session.class);
    }
}
