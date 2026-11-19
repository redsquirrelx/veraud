import java.io.*;

public class SessionLoader {
    public Object load(InputStream in) throws Exception {
        ObjectInputStream ois = new ObjectInputStream(in);
        return ois.readObject();
    }
}
