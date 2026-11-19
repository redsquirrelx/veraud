import java.io.*;

public class SessionLoader {
    public Object load(InputStream in) throws Exception {
        ObjectInputStream stream = new ObjectInputStream(new BufferedInputStream(in));
        return stream.readObject();
    }
}
