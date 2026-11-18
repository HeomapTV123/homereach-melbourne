package homereach.routing;

import com.conveyal.r5.profile.StreetMode;
import com.conveyal.r5.streets.EdgeStore;
import com.conveyal.r5.streets.Split;
import com.conveyal.r5.streets.StreetRouter;
import com.conveyal.r5.util.TIntObjectMultimap;
import java.lang.reflect.Field;
import java.util.Collection;
import java.util.PriorityQueue;

/** Experimental WALK-only origin initialization for the reviewed R5 binary.
 *
 * The caller has just invoked the original setOrigin, which establishes the
 * origin split and private heuristic metadata. No search has started. Rebuild
 * the initial queue and edge map together; never change costs of queued states.
 * Reflection is limited to the three reviewed fields of this pinned class.
 * It also avoids assuming package access across JPype's class loaders.
 */
public final class HomeReachStreetOrigins {
    private HomeReachStreetOrigins() { }

    private static Field field(Class<?> owner, String name) throws ReflectiveOperationException {
        Field result = owner.getDeclaredField(name);
        result.setAccessible(true);
        return result;
    }

    @SuppressWarnings("unchecked")
    public static int repairReverseOrigin(StreetRouter router) throws ReflectiveOperationException {
        if (router.streetMode != StreetMode.WALK) {
            throw new IllegalArgumentException("Origin correction supports WALK only.");
        }
        if (!router.profileRequest.reverseSearch) return 0;
        Split split = router.getOriginSplit();
        if (split == null || router.getDestinationSplit() != null) {
            throw new IllegalStateException("Expected a fresh reverse origin without a point destination.");
        }
        PriorityQueue<StreetRouter.State> queue = (PriorityQueue<StreetRouter.State>)
                field(StreetRouter.class, "queue").get(router);
        TIntObjectMultimap<StreetRouter.State> best = (TIntObjectMultimap<StreetRouter.State>)
                field(StreetRouter.class, "bestStatesAtEdge").get(router);
        Collection<StreetRouter.State> even = best.get(split.edge);
        Collection<StreetRouter.State> odd = best.get(split.edge + 1);
        if (queue.size() != 2 || even.size() != 1 || odd.size() != 1) {
            throw new IllegalStateException("Initial reverse queue/map shape differs from the reviewed implementation.");
        }
        StreetRouter.State oldEven = even.iterator().next();
        StreetRouter.State oldOdd = odd.iterator().next();
        if (oldEven.vertex != split.vertex0 || oldOdd.vertex != split.vertex1
                || oldEven.backEdge != split.edge || oldOdd.backEdge != split.edge + 1
                || oldEven.backState != null || oldOdd.backState != null
                || oldEven.turnRestrictions != null || oldOdd.turnRestrictions != null
                || !queue.contains(oldEven) || !queue.contains(oldOdd)) {
            throw new IllegalStateException("Expected only the original two untraversed WALK states.");
        }
        double walkSpeed = router.profileRequest.walkSpeed;
        if (!Double.isFinite(walkSpeed) || walkSpeed < 0.001) {
            throw new IllegalArgumentException("Walking speed must produce positive millimetres per second.");
        }
        int offStreetTime = split.distanceToEdge_mm / (int) (walkSpeed * 1000);
        StreetRouter.State state0 = initialState(router, split.vertex0, split.edge,
                split.distance0_mm, split.distanceToEdge_mm, offStreetTime);
        StreetRouter.State state1 = initialState(router, split.vertex1, split.edge + 1,
                split.distance1_mm, split.distanceToEdge_mm, offStreetTime);

        // Mutate collection membership only after both new states are valid.
        queue.clear();
        best.clear();
        queue.add(state0);
        queue.add(state1);
        best.put(state0.backEdge, state0);
        best.put(state1.backEdge, state1);
        return 2;
    }

    private static StreetRouter.State initialState(StreetRouter router, int vertex, int edgeId,
            int alongMm, int offMm, int offSeconds) throws ReflectiveOperationException {
        EdgeStore.Edge edge = router.streetLayer.edgeStore.getCursor(edgeId);
        float speed = edge.calculateSpeed(router.profileRequest, StreetMode.WALK);
        if (!Float.isFinite(speed) || speed <= 0 || alongMm < 0 || offMm < 0) {
            throw new IllegalArgumentException("Invalid directional edge speed or split distance.");
        }
        StreetRouter.State state = new StreetRouter.State(vertex, edgeId, StreetMode.WALK);
        state.distance = Math.addExact(alongMm, offMm);
        // Retain the pinned integer time conversion and origin-duration semantics.
        int seconds = Math.addExact((int) ((alongMm / 1000) / speed), offSeconds);
        field(StreetRouter.State.class, "durationSeconds").setInt(state, seconds);
        return state;
    }
}
